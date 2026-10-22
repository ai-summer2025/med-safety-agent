"""CDS Hooks 2.0 service for medsafe (FastAPI).

  GET  /cds-services                       discovery
  POST /cds-services/medsafe-order-sign    hook: order-sign   (cards only for the orders being signed)
  POST /cds-services/medsafe-patient-view  hook: patient-view (whole-list review, incl. reconciliation)
  POST /cds-services/{id}/feedback         card outcome feedback (accepted / overridden)

Configuration (environment):
  MEDSAFE_AUTH               "required" (default) or "disabled" (local development only)
  MEDSAFE_TRUSTED_ISSUERS    JSON object {"<iss>": "<JWKS url>"}
  MEDSAFE_PUBLIC_BASE_URL    external base URL, used as the expected JWT audience behind a proxy
  MEDSAFE_CORS_ORIGINS       comma-separated origins (default "*")
  MEDSAFE_EGFR_MAX_AGE_DAYS  default 90
  MEDSAFE_AUDIT_LOG          JSONL file for issued cards and feedback (default: medsafe-audit.jsonl)

The audit log records hookInstance, rule and drug names, never patient identifiers.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from ..fhir import patient_from_fhir, run_fhir
from ..models import Severity
from .auth import AuthError, Verifier
from .cards import data_gap_card, finding_card, summary_card

log = logging.getLogger("medsafe.cds")

EGFR_QUERY = ("Observation?patient={{context.patientId}}&code=http://loinc.org|98979-8,http://loinc.org|62238-1,"
              "http://loinc.org|33914-3,http://loinc.org|48642-3,http://loinc.org|48643-1&_sort=-date&_count=5")
PREFETCH = {
    "patient": "Patient/{{context.patientId}}",
    "medications": "MedicationRequest?patient={{context.patientId}}&status=active",
    "allergies": "AllergyIntolerance?patient={{context.patientId}}",
    "conditions": "Condition?patient={{context.patientId}}",
    "egfr": EGFR_QUERY,
}
PATIENT_VIEW_PREFETCH = {**PREFETCH, "homeMedications": "MedicationStatement?patient={{context.patientId}}"}
REQUIRED = {"patient", "medications"}

SERVICES = {
    "medsafe-order-sign": {
        "hook": "order-sign",
        "title": "Medication safety check",
        "description": "Checks medication orders being signed for interactions, Beers 2023 criteria, renal dosing, "
                       "dose limits, allergy conflicts and duplicate therapy, against the patient's active list.",
        "prefetch": PREFETCH,
    },
    "medsafe-patient-view": {
        "hook": "patient-view",
        "title": "Medication list review",
        "description": "Reviews the active medication list, including reconciliation against home medications.",
        "prefetch": PATIENT_VIEW_PREFETCH,
    },
}
PRIORITY = (Severity.CONTRAINDICATED, Severity.MAJOR, Severity.MODERATE)


@dataclass
class Settings:
    auth_required: bool = True
    trusted_issuers: Dict[str, str] = field(default_factory=dict)
    public_base_url: Optional[str] = None
    cors_origins: List[str] = field(default_factory=lambda: ["*"])
    egfr_max_age_days: int = 90
    audit_log: Path = Path("medsafe-audit.jsonl")

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            auth_required=os.environ.get("MEDSAFE_AUTH", "required").lower() != "disabled",
            trusted_issuers=json.loads(os.environ.get("MEDSAFE_TRUSTED_ISSUERS", "{}")),
            public_base_url=os.environ.get("MEDSAFE_PUBLIC_BASE_URL"),
            cors_origins=[o.strip() for o in os.environ.get("MEDSAFE_CORS_ORIGINS", "*").split(",")],
            egfr_max_age_days=int(os.environ.get("MEDSAFE_EGFR_MAX_AGE_DAYS", "90")),
            audit_log=Path(os.environ.get("MEDSAFE_AUDIT_LOG", "medsafe-audit.jsonl")),
        )


def fetch_fhir(base: str, query: str, token: str, max_pages: int = 5) -> List[dict]:
    """Fetch a resource or search (following next links) from the EHR's FHIR server."""
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/fhir+json"}
    url, out = f"{base.rstrip('/')}/{query}", []
    with httpx.Client(timeout=5) as client:
        for _ in range(max_pages):
            r = client.get(url, headers=headers)
            r.raise_for_status()
            data = r.json()
            out.append(data)
            nxt = [link["url"] for link in data.get("link", []) if link.get("relation") == "next"]
            if data.get("resourceType") != "Bundle" or not nxt:
                break
            url = nxt[0]
    return out


def create_app(settings: Optional[Settings] = None,
               fhir_fetcher: Callable[[str, str, str], List[dict]] = fetch_fhir,
               verifier: Optional[Verifier] = None,
               today: Callable[[], date] = date.today) -> FastAPI:
    settings = settings or Settings.from_env()
    verifier = verifier or Verifier(settings.trusted_issuers)
    app = FastAPI(title="medsafe CDS Hooks service", version="1.1.0")
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["GET", "POST", "OPTIONS"],
                       allow_headers=["Authorization", "Content-Type"])

    def audit(event: dict) -> None:
        event = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **event}
        with Path(settings.audit_log).open("a") as fh:
            fh.write(json.dumps(event) + "\n")

    def authenticate(request: Request) -> None:
        if not settings.auth_required:
            return
        base = settings.public_base_url.rstrip("/") if settings.public_base_url else str(request.base_url).rstrip("/")
        try:
            verifier.verify(request.headers.get("authorization"), audience=base + request.url.path)
        except AuthError as e:
            raise HTTPException(status_code=401, detail=str(e)) from e

    @app.get("/cds-services")
    def discovery():
        return {"services": [{"id": sid, **spec} for sid, spec in SERVICES.items()]}

    @app.post("/cds-services/{service_id}")
    async def invoke(service_id: str, request: Request):
        if service_id not in SERVICES:
            raise HTTPException(status_code=404, detail="unknown service")
        authenticate(request)
        try:
            body = await request.json()
        except ValueError as e:
            raise HTTPException(status_code=400, detail="request body is not JSON") from e
        spec = SERVICES[service_id]
        context = body.get("context") or {}
        if body.get("hook") != spec["hook"] or not body.get("hookInstance") or not context.get("patientId"):
            raise HTTPException(status_code=400, detail="hook, hookInstance and context.patientId are required")

        prefetch = body.get("prefetch") or {}
        resources, missing = [], []
        for key, template in spec["prefetch"].items():
            if key in prefetch:
                if prefetch[key] is not None:  # null = the EHR has no such data
                    resources.append(prefetch[key])
            elif body.get("fhirServer") and (body.get("fhirAuthorization") or {}).get("access_token"):
                query = template.replace("{{context.patientId}}", context["patientId"])
                try:
                    resources += fhir_fetcher(body["fhirServer"], query, body["fhirAuthorization"]["access_token"])
                except httpx.HTTPError as e:
                    log.warning("FHIR fetch failed for %s: %s", key, e)
                    missing.append(key)
            else:
                missing.append(key)
        if REQUIRED & set(missing):
            raise HTTPException(status_code=412, detail=f"required data unavailable: {sorted(REQUIRED & set(missing))}")

        drafts = context.get("draftOrders") if spec["hook"] == "order-sign" else None
        try:
            ctx = patient_from_fhir(resources, as_of=today(), draft_orders=[drafts] if drafts else [],
                                    egfr_max_age_days=settings.egfr_max_age_days)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        report = run_fhir(ctx)

        if spec["hook"] == "order-sign":
            relevant = [f for f in report.findings
                        if set(f.drugs) & ctx.draft_drugs and f.category != "reconciliation"]
            cards = [finding_card(f, ctx, suggest_removal=True) for f in relevant if f.severity in PRIORITY]
            low = [f for f in relevant if f.severity not in PRIORITY]
        else:
            cards = [finding_card(f, ctx, suggest_removal=False) for f in report.findings if f.severity in PRIORITY]
            low = [f for f in report.findings if f.severity not in PRIORITY]
        if low:
            cards.append(summary_card(low))
        if missing and (cards or spec["hook"] == "patient-view"):
            cards.append(data_gap_card(missing))
        for card in cards:
            topic = (card.get("source") or {}).get("topic") or {}
            audit({"event": "card", "service": service_id, "hookInstance": body["hookInstance"],
                   "card": card["uuid"], "rule": topic.get("code"), "indicator": card["indicator"]})
        return {"cards": cards}

    @app.post("/cds-services/{service_id}/feedback")
    async def feedback(service_id: str, request: Request):
        if service_id not in SERVICES:
            raise HTTPException(status_code=404, detail="unknown service")
        authenticate(request)
        body = await request.json()
        items = body.get("feedback")
        if not isinstance(items, list) or not all(isinstance(i, dict) and i.get("card") and
                                                  i.get("outcome") in ("accepted", "overridden") for i in items):
            raise HTTPException(status_code=400, detail="feedback must be a list of {card, outcome}")
        for item in items:
            audit({"event": "feedback", "service": service_id, "card": item["card"], "outcome": item["outcome"],
                   "overrideReason": ((item.get("overrideReason") or {}).get("reason") or {}).get("code"),
                   "acceptedSuggestions": [s.get("id") for s in item.get("acceptedSuggestions") or []]})
        return {}

    return app


def main() -> None:  # pragma: no cover - thin wrapper
    import uvicorn
    uvicorn.run(create_app(), host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", "8080")))
