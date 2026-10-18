"""Deterministic safety checks. Each returns a list of Findings.

These functions are pure: same input, same output, no network, no LLM.
That is deliberate. Clinical decisions in this tool never depend on a
language model; the LLM is only used upstream to turn free text into the
structured `Patient` these checks consume (see `extract.py`).
"""
from __future__ import annotations

from itertools import combinations
from typing import Dict, List

from .knowledge import rules as R
from .knowledge.vocab import CLASSES, INTENTIONAL_COMBINATION_CLASSES, NOT_DUPLICATE_CLASSES, classes_of, matches
from .models import Finding, Medication, Patient, Severity


def _names(meds: List[Medication]) -> List[str]:
    seen, out = set(), []
    for m in meds:
        if m.name not in seen:
            seen.add(m.name)
            out.append(m.name)
    return out


def check_interactions(patient: Patient) -> List[Finding]:
    findings: List[Finding] = []
    names = _names(patient.medications)
    for x, y in combinations(names, 2):
        for rule in R.INTERACTIONS:
            if (matches(x, rule.a) and matches(y, rule.b)) or (matches(y, rule.a) and matches(x, rule.b)):
                findings.append(Finding(rule.id, "interaction", rule.severity, [x, y],
                                        rule.message, rule.recommendation, rule.source))

    # Three-drug rule: RAAS blocker + diuretic + NSAID
    raas = [n for n in names if matches(n, "class:ace_inhibitor") or matches(n, "class:arb")]
    diur = [n for n in names if matches(n, "class:loop_diuretic") or matches(n, "class:thiazide")
            or matches(n, "class:potassium_sparing_diuretic")]
    nsaid = [n for n in names if matches(n, "class:nsaid")]
    if raas and diur and nsaid:
        findings.append(Finding(
            "DDI-TRIPLE-WHAMMY", "interaction", Severity.MAJOR, [raas[0], diur[0], nsaid[0]],
            "ACE inhibitor/ARB + diuretic + NSAID ('triple whammy'): increased risk of acute kidney injury.",
            "Stop the NSAID if possible; otherwise monitor creatinine and volume status closely.",
            R.TRIPLE_WHAMMY_SOURCE))
    return findings


def check_duplicates(patient: Patient) -> List[Finding]:
    findings: List[Finding] = []
    counts: Dict[str, int] = {}
    for m in patient.medications:
        counts[m.name] = counts.get(m.name, 0) + 1
    for name, n in counts.items():
        if n > 1:
            findings.append(Finding("DUP-SAME-DRUG", "duplicate", Severity.MAJOR, [name],
                                    f"{name} appears {n} times on the list.",
                                    "Confirm a single intended order and total daily dose.",
                                    "Medication reconciliation best practice (Joint Commission NPSG.03.06.01)"))
    names = _names(patient.medications)
    for cls, members in CLASSES.items():
        if cls in NOT_DUPLICATE_CLASSES:
            continue
        in_cls = sorted(n for n in names if n in members)
        if len(in_cls) >= 2:
            intentional = cls in INTENTIONAL_COMBINATION_CLASSES
            findings.append(Finding(
                f"DUP-CLASS-{cls.upper()}", "duplicate",
                Severity.MINOR if intentional else Severity.MAJOR, in_cls,
                f"Two or more drugs from the same class ({cls.replace('_', ' ')}): {', '.join(in_cls)}.",
                "Verify this combination is intended and documented." if intentional
                else "Likely therapeutic duplication; confirm and keep one agent.",
                "Therapeutic duplication check"))
    return findings


def check_beers(patient: Patient) -> List[Finding]:
    if patient.age < R.BEERS_AGE:
        return []
    findings: List[Finding] = []
    for m in patient.medications:
        for rule in R.BEERS:
            if not matches(m.name, rule.spec):
                continue
            if rule.min_daily_mg is not None:
                daily = m.daily_dose_mg
                if daily is None or daily <= rule.min_daily_mg:
                    continue
            findings.append(Finding(rule.id, "beers", rule.severity, [m.name],
                                    rule.message, rule.recommendation, R.BEERS_SOURCE))
    conditions = " | ".join(c.lower() for c in patient.conditions)
    for rule_id, keyword, spec, message in R.BEERS_CONDITION:
        if keyword in conditions:
            for m in patient.medications:
                if matches(m.name, spec):
                    findings.append(Finding(rule_id, "beers", Severity.MAJOR, [m.name], message,
                                            "Avoid in this condition; review alternatives.",
                                            R.BEERS_SOURCE))
    return _dedupe(findings)


def check_renal(patient: Patient) -> List[Finding]:
    if patient.egfr is None:
        return []
    findings: List[Finding] = []
    for name in _names(patient.medications):
        hits = [r for r in R.RENAL if matches(name, r.spec) and patient.egfr < r.egfr_below]
        if not hits:
            continue
        # Report only the strictest threshold for each drug.
        rule = min(hits, key=lambda r: r.egfr_below)
        findings.append(Finding(rule.id, "renal", rule.severity, [name],
                                f"{rule.message} (eGFR {patient.egfr:g})",
                                rule.recommendation, rule.source))
    return findings


def check_anticholinergic_burden(patient: Patient) -> List[Finding]:
    scored = {n: R.ACB_SCORES[n] for n in _names(patient.medications) if n in R.ACB_SCORES}
    total = sum(scored.values())
    if total < R.ACB_THRESHOLD:
        return []
    severity = Severity.MAJOR if (total >= 3 and patient.age >= 65) or total >= 6 else Severity.MODERATE
    contributors = sorted(n for n, s in scored.items() if s > 0)
    detail = ", ".join(f"{n} ({scored[n]})" for n in contributors)
    return [Finding("ACB-BURDEN", "anticholinergic", severity, contributors,
                    f"Total anticholinergic burden score {total}: {detail}. "
                    "A score of 3 or more is associated with cognitive impairment and higher mortality.",
                    "Deprescribe or substitute the highest-scoring agents where possible.", "ACB")]


def check_doses(patient: Patient) -> List[Finding]:
    findings: List[Finding] = []
    totals: Dict[str, float] = {}
    for m in patient.medications:
        d = m.daily_dose_mg
        if d is not None:
            totals[m.name] = totals.get(m.name, 0.0) + d
    for m in patient.medications:
        # Classic, sometimes fatal error: oral methotrexate for non-cancer use is weekly.
        if m.name == "methotrexate" and m.doses_per_day is not None and m.doses_per_day >= 1 \
                and m.route in (None, "oral"):
            findings.append(Finding(
                "DOSE-MTX-DAILY", "dose", Severity.MAJOR, ["methotrexate"],
                "Oral methotrexate ordered daily. For non-oncology indications it is dosed once weekly; "
                "daily dosing has caused fatal toxicity.",
                "Confirm the indication and change to a once-weekly schedule unless an oncology protocol "
                "specifies otherwise.",
                "ISMP targeted medication safety best practice; FDA-LABEL (methotrexate)"))
    for name, total in totals.items():
        limit = R.DOSE_MAX_MG.get(name)
        age_rule = R.DOSE_MAX_BY_AGE.get(name)
        if age_rule and patient.age >= age_rule[0]:
            limit = (age_rule[1], age_rule[2])
        if limit and total > limit[0]:
            findings.append(Finding("DOSE-ABOVE-MAX", "dose", Severity.MAJOR, [name],
                                    f"{name} scheduled total {total:g} mg/day exceeds the maximum of "
                                    f"{limit[0]:g} mg/day.",
                                    "Verify the dose and frequency.", limit[1]))
    return findings


def check_allergies(patient: Patient) -> List[Finding]:
    findings: List[Finding] = []
    allergies = [a.lower() for a in patient.allergies]
    for allergy_key, entries in R.ALLERGY.items():
        if not any(allergy_key in a for a in allergies):
            continue
        for name in _names(patient.medications):
            for spec, severity, message in entries:
                if matches(name, spec):
                    findings.append(Finding(f"ALLERGY-{allergy_key.upper().replace(' ', '-')}",
                                            "allergy", severity, [name], message,
                                            "Confirm the allergy history and reaction type before administering.",
                                            R.ALLERGY_SOURCE))
                    break
    # Direct match: allergy text names the drug itself.
    for name in _names(patient.medications):
        if any(name == a or name in a.split() for a in allergies):
            findings.append(Finding("ALLERGY-DIRECT", "allergy", Severity.CONTRAINDICATED, [name],
                                    f"{name} is listed in the patient's allergies.",
                                    "Do not administer; confirm the allergy record.", R.ALLERGY_SOURCE))
    return _dedupe(findings)


def check_reconciliation(patient: Patient) -> List[Finding]:
    """Compare pre-admission (home) list against the current/discharge list."""
    if not patient.home_medications:
        return []
    findings: List[Finding] = []
    current = {m.name: m for m in patient.medications}
    stopped = {s.lower() for s in patient.intentionally_stopped}
    for h in patient.home_medications:
        if h.name in stopped:
            continue
        if h.name not in current:
            high_risk = h.name in R.HIGH_RISK_OMISSION_DRUGS or bool(
                classes_of(h.name) & R.HIGH_RISK_OMISSION_CLASSES)
            findings.append(Finding(
                "RECON-OMISSION", "reconciliation",
                Severity.MAJOR if high_risk else Severity.MODERATE, [h.name],
                f"Home medication {h.name} is not on the current list and is not documented as stopped.",
                "Resume, or document the reason it was stopped and tell the patient.",
                "Medication reconciliation (Joint Commission NPSG.03.06.01)"))
            continue
        c = current[h.name]
        if h.daily_dose_mg is not None and c.daily_dose_mg is not None and \
                abs(h.daily_dose_mg - c.daily_dose_mg) > 1e-9:
            findings.append(Finding(
                "RECON-DOSE-CHANGE", "reconciliation", Severity.MINOR, [h.name],
                f"{h.name} daily dose changed from {h.daily_dose_mg:g} mg to {c.daily_dose_mg:g} mg.",
                "Make sure the change is intended and is explained in the discharge instructions.",
                "Medication reconciliation (Joint Commission NPSG.03.06.01)"))
    home = {h.name for h in patient.home_medications}
    for name in current:
        if name not in home:
            findings.append(Finding("RECON-NEW", "reconciliation", Severity.INFO, [name],
                                    f"{name} is new since admission.",
                                    "Include indication and duration in discharge instructions.",
                                    "Medication reconciliation (Joint Commission NPSG.03.06.01)"))
    return findings


def _dedupe(findings: List[Finding]) -> List[Finding]:
    seen, out = set(), []
    for f in findings:
        if f.key not in seen:
            seen.add(f.key)
            out.append(f)
    return out


ALL_CHECKS = [
    check_interactions, check_duplicates, check_beers, check_renal,
    check_anticholinergic_burden, check_doses, check_allergies, check_reconciliation,
]
