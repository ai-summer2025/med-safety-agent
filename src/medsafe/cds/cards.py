"""medsafe findings -> CDS Hooks 2.0 cards."""
from __future__ import annotations

import uuid
from typing import List

from ..fhir.adapter import FhirContext
from ..models import Finding, Severity

RULES_URL = "https://github.com/ai-summer2025/med-safety-agent/blob/main/src/medsafe/knowledge/rules.py"
INDICATOR = {Severity.CONTRAINDICATED: "critical", Severity.MAJOR: "warning", Severity.MODERATE: "warning",
             Severity.MINOR: "info", Severity.INFO: "info"}
OVERRIDE_SYSTEM = "https://github.com/ai-summer2025/med-safety-agent/override-reasons"
OVERRIDE_REASONS = [
    {"system": OVERRIDE_SYSTEM, "code": "benefit-outweighs-risk", "display": "Benefit outweighs risk"},
    {"system": OVERRIDE_SYSTEM, "code": "will-monitor", "display": "Will monitor or adjust"},
    {"system": OVERRIDE_SYSTEM, "code": "tolerated-previously", "display": "Patient has tolerated this before"},
    {"system": OVERRIDE_SYSTEM, "code": "data-incorrect", "display": "Patient data is incorrect or outdated"},
]
LABEL = {Severity.CONTRAINDICATED: "Contraindicated", Severity.MAJOR: "Major", Severity.MODERATE: "Moderate",
         Severity.MINOR: "Minor", Severity.INFO: "Info"}


def _summary(f: Finding) -> str:
    text = f"{LABEL[f.severity]}: {f.message}"
    return text if len(text) < 140 else text[:136].rstrip() + "..."


def _detail(f: Finding, ctx: FhirContext) -> str:
    lines = [f.message, "", f"**Recommendation:** {f.recommendation}", "",
             f"**Rule:** `{f.rule_id}`  **Source:** {f.source}"]
    if f.category == "renal" and ctx.egfr_used:
        lines += ["", f"**eGFR used:** {ctx.egfr_used[0]} on {ctx.egfr_used[1]} (LOINC {ctx.egfr_used[2]})"]
    lines += ["", "_Decision support only; requires clinical review._"]
    return "\n".join(lines)


def finding_card(f: Finding, ctx: FhirContext, suggest_removal: bool) -> dict:
    card = {
        "uuid": str(uuid.uuid4()),
        "summary": _summary(f),
        "detail": _detail(f, ctx),
        "indicator": INDICATOR[f.severity],
        "source": {"label": "medsafe medication safety rules", "url": RULES_URL,
                   "topic": {"system": RULES_URL, "code": f.rule_id, "display": f.category}},
    }
    drafts = [(d, ctx.draft_refs[d]) for d in f.drugs if d in ctx.draft_refs]
    if suggest_removal and drafts and f.severity in (Severity.CONTRAINDICATED, Severity.MAJOR):
        card["suggestions"] = [{
            "label": f"Remove the new {d} order",
            "uuid": str(uuid.uuid4()),
            "isRecommended": f.severity is Severity.CONTRAINDICATED,
            "actions": [{"type": "delete", "description": f"Remove draft order for {d}", "resourceId": ref}],
        } for d, ref in drafts]
        card["selectionBehavior"] = "at-most-one"
    if f.severity in (Severity.CONTRAINDICATED, Severity.MAJOR, Severity.MODERATE):
        card["overrideReasons"] = OVERRIDE_REASONS
    return card


def summary_card(findings: List[Finding]) -> dict:
    """One info card for lower-priority findings, to limit alert fatigue."""
    body = "\n".join(f"- **{LABEL[f.severity]}** {f.message} (`{f.rule_id}`)" for f in findings)
    return {
        "uuid": str(uuid.uuid4()),
        "summary": f"{len(findings)} lower-priority medication review item{'s' if len(findings) != 1 else ''}",
        "detail": body + "\n\n_Decision support only; requires clinical review._",
        "indicator": "info",
        "source": {"label": "medsafe medication safety rules", "url": RULES_URL},
    }


def data_gap_card(missing: List[str]) -> dict:
    return {
        "uuid": str(uuid.uuid4()),
        "summary": "Medication safety check ran with incomplete data",
        "detail": "Not available to the service: " + ", ".join(missing)
                  + ". Checks that depend on these were skipped, not passed.",
        "indicator": "info",
        "source": {"label": "medsafe medication safety rules", "url": RULES_URL},
    }
