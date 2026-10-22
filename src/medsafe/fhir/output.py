"""Run medsafe on FHIR input, and express findings as FHIR R4 DetectedIssue resources."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Iterable, List, Optional

from ..models import Finding, Severity
from ..pipeline import Report, run
from .adapter import FhirContext, Note

# HL7 v3 ActCode detected-issue codes, used only where the meaning matches.
ACTCODE = "http://terminology.hl7.org/CodeSystem/v3-ActCode"
ISSUE_CODE = {
    "interaction": ("DRG", "Drug Interaction Alert"),
    "duplicate": ("DUPTHPY", "Duplicate Therapy Alert"),
    "allergy": ("ALGY", "Allergy Alert"),
    "dose": ("DOSEH", "High Dose Alert"),
    "beers": ("AGE", "Age Alert"),
    "renal": ("COND", "Condition Alert"),
}
SEVERITY = {Severity.CONTRAINDICATED: "high", Severity.MAJOR: "high", Severity.MODERATE: "moderate",
            Severity.MINOR: "low", Severity.INFO: "low"}


def run_fhir(ctx: FhirContext) -> Report:
    """Run all checks, then drop class-duplicate findings produced by a single combination product
    (e.g. premixed insulin 70/30 lists two insulins but is one order)."""
    report = run(ctx.patient, extraction_method="fhir")
    kept: List[Finding] = []
    for f in report.findings:
        if f.category == "duplicate" and f.rule_id.startswith("DUP-CLASS-") and len(f.drugs) > 1:
            refs = {tuple(sorted(ctx.sources.get(d, []))) for d in f.drugs}
            if len(refs) == 1 and len(next(iter(refs))) == 1:
                ctx.notes.append(Note(next(iter(refs))[0], f"{f.rule_id} suppressed: single combination product"))
                continue
        kept.append(f)
    report.findings = kept
    return report


def detected_issues(report: Report, ctx: FhirContext, now: Optional[datetime] = None) -> List[dict]:
    now = now or datetime.now(timezone.utc)
    out = []
    for f in report.findings:
        issue = {
            "resourceType": "DetectedIssue",
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"medsafe/{ctx.patient.id}/{f.rule_id}/{'+'.join(f.drugs)}")),
            "status": "preliminary",
            "severity": SEVERITY[f.severity],
            "patient": {"reference": f"Patient/{ctx.patient.id}"},
            "identifiedDateTime": now.isoformat(timespec="seconds"),
            "author": {"display": "medsafe"},
            "implicated": [{"reference": ref} for d in f.drugs for ref in ctx.sources.get(d, [])],
            "detail": f"{f.message} Recommendation: {f.recommendation} (rule {f.rule_id}; source: {f.source})",
            "code": {"text": f.category},
        }
        if f.category in ISSUE_CODE:
            code, display = ISSUE_CODE[f.category]
            issue["code"]["coding"] = [{"system": ACTCODE, "code": code, "display": display}]
        out.append(issue)
    return out


def as_bundle(resources: Iterable[dict]) -> dict:
    return {"resourceType": "Bundle", "type": "collection",
            "entry": [{"fullUrl": f"urn:uuid:{r['id']}", "resource": r} for r in resources]}
