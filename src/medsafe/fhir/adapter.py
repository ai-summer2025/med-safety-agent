"""FHIR R4 (US Core) resources -> medsafe Patient.

Every resource is either used or recorded in `FhirContext.notes` with the reason it was
skipped, so a reviewer can see exactly what the checks were based on.

Status rules (the part most integrations get wrong):
  MedicationRequest   active (current list) or draft (orders being signed); skip doNotPerform,
                      intent=proposal, and every other status
  MedicationStatement active/intended/unknown -> home list; stopped -> documented stop
  AllergyIntolerance  skip clinicalStatus inactive/resolved and verificationStatus refuted/entered-in-error
  Condition           only clinicalStatus active/recurrence/relapse; skip refuted/entered-in-error
  Observation (eGFR)  final/amended/corrected; most recent within `egfr_max_age_days`
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Optional, Set, Tuple

from ..models import Medication, Patient
from .terminology import EGFR_LOINC, EGFR_UNITS, LOINC, allergy_labels, codes_in, condition_labels, resolve_medication

ACTIVE_REQUEST = {"active"}
ORDER_INTENTS = {"order", "original-order", "reflex-order", "filler-order", "instance-order", "plan"}
HOME_STATEMENT = {"active", "intended", "unknown"}
OBS_FINAL = {"final", "amended", "corrected"}
TIMING_CODES = {"QD": 1, "BID": 2, "TID": 3, "QID": 4, "QOD": 0.5, "Q4H": 6, "Q6H": 4, "Q8H": 3,
                "Q12H": 2, "AM": 1, "PM": 1, "WK": 1 / 7}
PERIOD_PER_DAY = {"s": 86400, "min": 1440, "h": 24, "d": 1, "wk": 1 / 7, "mo": 1 / 30, "a": 1 / 365}
MASS_UNITS = {"mg": 1.0, "ug": 0.001, "mcg": 0.001, "g": 1000.0}


@dataclass
class Note:
    resource: str
    reason: str


@dataclass
class FhirContext:
    patient: Patient
    as_of: date
    notes: List[Note] = field(default_factory=list)
    # medsafe drug name -> FHIR references of the resources it came from
    sources: Dict[str, List[str]] = field(default_factory=dict)
    draft_drugs: Set[str] = field(default_factory=set)
    draft_refs: Dict[str, str] = field(default_factory=dict)  # drug -> MedicationRequest ref of the draft
    egfr_used: Optional[Tuple[float, str, str]] = None  # value, date, LOINC code


def iter_resources(*items) -> Iterable[dict]:
    """Flatten resources, Bundles (any type) and lists of either."""
    for item in items:
        if not item:
            continue
        if isinstance(item, list):
            yield from iter_resources(*item)
        elif item.get("resourceType") == "Bundle":
            for e in item.get("entry") or []:
                if e.get("resource"):
                    r = e["resource"]
                    if e.get("fullUrl") and r.get("resourceType") != "Bundle":
                        r = {**r, "_fullUrl": e["fullUrl"]}
                    yield from iter_resources(r)
        elif item.get("resourceType") == "OperationOutcome":
            continue
        else:
            yield item


def _ref(r: dict) -> str:
    return f"{r.get('resourceType')}/{r.get('id', '?')}"


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date() if "T" in s else date.fromisoformat(s[:10])
    except ValueError:
        return None


def _status(cc: Optional[dict]) -> Optional[str]:
    for c in (cc or {}).get("coding") or []:
        if c.get("code"):
            return c["code"]
    return None


def latest_clinical_date(resources: Iterable[dict]) -> Optional[date]:
    best = None
    for r in resources:
        for key in ("authoredOn", "effectiveDateTime", "recordedDate", "onsetDateTime", "issued"):
            d = _parse_date(r.get(key))
            if d and (best is None or d > best):
                best = d
    return best


class _Index:
    def __init__(self, resources: List[dict]):
        self.by_ref: Dict[str, dict] = {}
        for r in resources:
            self.by_ref[_ref(r)] = r
            if r.get("_fullUrl"):
                self.by_ref[r["_fullUrl"]] = r

    def medication_concept(self, req: dict) -> Optional[dict]:
        if req.get("medicationCodeableConcept"):
            return req["medicationCodeableConcept"]
        ref = (req.get("medicationReference") or {}).get("reference", "")
        if ref.startswith("#"):
            for c in req.get("contained") or []:
                if c.get("id") == ref[1:]:
                    return c.get("code")
        target = self.by_ref.get(ref)
        return (target or {}).get("code")


def _doses_per_day(dosage: dict) -> Tuple[Optional[float], bool]:
    """(scheduled doses per day, prn). PRN-only orders return (None, True), matching medsafe's convention."""
    prn = bool(dosage.get("asNeededBoolean")) or bool(dosage.get("asNeededCodeableConcept"))
    timing = dosage.get("timing") or {}
    rep = timing.get("repeat") or {}
    per_day = None
    if rep.get("period") and rep.get("periodUnit") in PERIOD_PER_DAY:
        per_day = (rep.get("frequency") or 1) * PERIOD_PER_DAY[rep["periodUnit"]] / float(rep["period"])
    elif rep.get("when"):
        per_day = float(len(rep["when"]))
    else:
        code = _status(timing.get("code"))
        if code in TIMING_CODES:
            per_day = float(TIMING_CODES[code])
    return (None if prn else per_day), prn


def _dose_mg(dosage: dict, mg_per_unit: Optional[float]) -> Optional[float]:
    for dr in dosage.get("doseAndRate") or []:
        q = dr.get("doseQuantity")
        if q is None and dr.get("doseRange"):
            q = dr["doseRange"].get("high")  # upper bound for maximum-dose checks
        if not q or q.get("value") is None:
            continue
        unit = (q.get("code") or q.get("unit") or "").strip().lower()
        if unit in MASS_UNITS:
            return float(q["value"]) * MASS_UNITS[unit]
        if mg_per_unit is not None and unit in ("", "1", "{tbl}", "{tablet}", "tab", "tablet", "{capsule}", "cap",
                                                 "capsule", "{dose}"):
            return float(q["value"]) * mg_per_unit
    return None


def _medications(resource: dict, concept: Optional[dict], dosage: Optional[dict],
                 ctx: FhirContext) -> List[Medication]:
    drug = resolve_medication(concept)
    if not drug.ingredients:
        ctx.notes.append(Note(_ref(resource), f"medication not resolved ({drug.note}): {drug.display}"))
        return []
    if drug.note:
        ctx.notes.append(Note(_ref(resource), drug.note))
    per_day, prn = _doses_per_day(dosage or {})
    route = None
    for src in ((dosage or {}).get("route"), ):
        if src:
            route = (src.get("text") or _display(src) or "").lower() or None
    if route is None and drug.dose_form and "oral" in drug.dose_form.lower():
        route = "oral"
    elif route and "oral" in route:
        route = "oral"
    merged: Dict[str, Optional[float]] = {}
    for ing in drug.ingredients:  # same ingredient twice in one product (e.g. nitrofurantoin) -> one entry
        mg = ing.mg_per_unit if drug.countable else None
        if ing.name in merged and merged[ing.name] is not None and mg is not None:
            merged[ing.name] += mg
        elif ing.name not in merged:
            merged[ing.name] = mg
    meds = []
    multi = len(merged) > 1
    for name, mg_per_unit in merged.items():
        if multi:  # a mass dose on a combination product is ambiguous; a tablet count is not
            dose = _dose_mg(dosage or {}, mg_per_unit) if mg_per_unit is not None and _countable_dose(dosage) else None
        else:
            dose = _dose_mg(dosage or {}, mg_per_unit)
        meds.append(Medication(name=name, dose=dose, unit="mg" if dose is not None else None,
                               doses_per_day=per_day, route=route, prn=prn, raw=drug.display))
        ctx.sources.setdefault(name, []).append(_ref(resource))
    return meds


def _countable_dose(dosage: Optional[dict]) -> bool:
    for dr in (dosage or {}).get("doseAndRate") or []:
        q = dr.get("doseQuantity") or {}
        unit = (q.get("code") or q.get("unit") or "").strip().lower()
        if q.get("value") is not None and unit not in MASS_UNITS:
            return True
    return False


def _display(cc: Optional[dict]) -> Optional[str]:
    for c in (cc or {}).get("coding") or []:
        if c.get("display"):
            return c["display"]
    return (cc or {}).get("text")


def _age(birth: Optional[str], as_of: date) -> Optional[int]:
    b = _parse_date(birth)
    if not b:
        return None
    return as_of.year - b.year - ((as_of.month, as_of.day) < (b.month, b.day))


def patient_from_fhir(resources: Iterable[dict], as_of: Optional[date] = None, draft_orders: Iterable[dict] = (),
                      egfr_max_age_days: int = 90) -> FhirContext:
    resources = list(iter_resources(list(resources)))
    drafts = list(iter_resources(list(draft_orders)))
    as_of = as_of or date.today()
    idx = _Index(resources + drafts)
    pats = [r for r in resources if r.get("resourceType") == "Patient"]
    if not pats:
        raise ValueError("no Patient resource")
    p = pats[0]
    age = _age(p.get("birthDate"), as_of)
    if age is None:
        raise ValueError("Patient.birthDate missing or invalid; age is required for age-based rules")
    patient = Patient(id=p.get("id", "patient"), age=age, sex=p.get("gender"))
    ctx = FhirContext(patient=patient, as_of=as_of)
    if p.get("deceasedBoolean") or p.get("deceasedDateTime"):
        ctx.notes.append(Note(_ref(p), "patient is recorded as deceased"))

    egfr_candidates: List[Tuple[date, float, str, dict]] = []
    for r in resources:
        rt = r.get("resourceType")
        if rt == "MedicationRequest":
            if r.get("doNotPerform"):
                ctx.notes.append(Note(_ref(r), "doNotPerform order ignored"))
            elif r.get("status") not in ACTIVE_REQUEST:
                ctx.notes.append(Note(_ref(r), f"status {r.get('status')} ignored"))
            elif r.get("intent") not in ORDER_INTENTS:
                ctx.notes.append(Note(_ref(r), f"intent {r.get('intent')} ignored"))
            else:
                dosage = (r.get("dosageInstruction") or [None])[0]
                patient.medications += _medications(r, idx.medication_concept(r), dosage, ctx)
        elif rt == "MedicationStatement":
            status = r.get("status")
            concept = idx.medication_concept(r)
            dosage = (r.get("dosage") or [None])[0]
            if status in HOME_STATEMENT:
                patient.home_medications += _medications(r, concept, dosage, ctx)
            elif status == "stopped":
                patient.intentionally_stopped += [m.name for m in _medications(r, concept, dosage, ctx)]
            else:
                ctx.notes.append(Note(_ref(r), f"status {status} ignored"))
        elif rt == "AllergyIntolerance":
            clin, ver = _status(r.get("clinicalStatus")), _status(r.get("verificationStatus"))
            if clin in ("inactive", "resolved") or ver in ("refuted", "entered-in-error"):
                ctx.notes.append(Note(_ref(r), f"allergy ignored (clinical={clin}, verification={ver})"))
            else:
                patient.allergies += allergy_labels(r.get("code"))
        elif rt == "Condition":
            clin, ver = _status(r.get("clinicalStatus")), _status(r.get("verificationStatus"))
            if clin not in ("active", "recurrence", "relapse") or ver in ("refuted", "entered-in-error"):
                ctx.notes.append(Note(_ref(r), f"condition ignored (clinical={clin}, verification={ver})"))
            else:
                patient.conditions += condition_labels(r.get("code"))
        elif rt == "Observation":
            codes = [c for c in codes_in(r.get("code"), LOINC) if c in EGFR_LOINC]
            if not codes:
                continue
            q = r.get("valueQuantity") or {}
            when = _parse_date(r.get("effectiveDateTime") or (r.get("effectivePeriod") or {}).get("end")
                               or r.get("issued"))
            unit = q.get("code") or q.get("unit")
            if r.get("status") not in OBS_FINAL:
                ctx.notes.append(Note(_ref(r), f"eGFR status {r.get('status')} ignored"))
            elif q.get("value") is None or when is None:
                ctx.notes.append(Note(_ref(r), "eGFR without value or date ignored"))
            elif unit not in EGFR_UNITS:
                ctx.notes.append(Note(_ref(r), f"eGFR unit {unit} not recognised"))
            else:
                egfr_candidates.append((when, float(q["value"]), codes[0], r))

    if egfr_candidates:
        when, value, code, r = max(egfr_candidates, key=lambda t: t[0])
        if as_of - when > timedelta(days=egfr_max_age_days):
            ctx.notes.append(Note(_ref(r), f"latest eGFR ({when.isoformat()}) older than {egfr_max_age_days} days; "
                                           "renal checks skipped"))
        else:
            patient.egfr = round(value, 1)
            if (r.get("valueQuantity") or {}).get("comparator") in ("<", "<="):
                patient.egfr -= 1e-6  # "<15" means strictly below 15, so "below 15" rules must fire
            ctx.egfr_used = (round(value, 1), when.isoformat(), code)
    else:
        ctx.notes.append(Note("Observation", "no eGFR found; renal checks skipped"))

    for r in drafts:
        if r.get("resourceType") != "MedicationRequest":
            continue
        dosage = (r.get("dosageInstruction") or [None])[0]
        for m in _medications(r, idx.medication_concept(r), dosage, ctx):
            patient.medications.append(m)
            ctx.draft_drugs.add(m.name)
            ctx.draft_refs[m.name] = _ref(r)
    patient.allergies = list(dict.fromkeys(patient.allergies))
    patient.conditions = list(dict.fromkeys(patient.conditions))
    return ctx
