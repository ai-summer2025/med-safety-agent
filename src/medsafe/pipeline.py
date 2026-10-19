"""Orchestration: (optional) extraction -> deterministic checks -> report."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .checks import ALL_CHECKS
from .extract import extract_llm, extract_rules
from .knowledge.vocab import known_drugs, normalize_name
from .models import Finding, Medication, Patient, Severity


@dataclass
class Report:
    patient_id: str
    findings: List[Finding]
    unrecognized_drugs: List[str] = field(default_factory=list)
    extraction_method: Optional[str] = None

    @property
    def counts(self) -> Dict[str, int]:
        c = {s.value: 0 for s in Severity}
        for f in self.findings:
            c[f.severity.value] += 1
        return c

    def to_dict(self) -> dict:
        return {"patient_id": self.patient_id, "counts": self.counts,
                "extraction_method": self.extraction_method,
                "unrecognized_drugs": self.unrecognized_drugs,
                "findings": [f.to_dict() for f in self.findings]}


def run(patient: Patient, extraction_method: Optional[str] = None) -> Report:
    findings: List[Finding] = []
    for check in ALL_CHECKS:
        findings.extend(check(patient))
    findings.sort(key=lambda f: (f.severity.rank, f.category, f.rule_id))
    vocab = known_drugs()
    unknown = sorted({m.name for m in patient.medications + patient.home_medications
                      if m.name not in vocab})
    return Report(patient.id, findings, unknown, extraction_method)


def medications_from_text(text: str, use_llm: bool = False, client=None) -> List[Medication]:
    if use_llm:
        if client is None:
            from .llm import client_from_env
            client = client_from_env()
        return extract_llm(text, client)
    return extract_rules(text)


def _med_from_dict(d: dict) -> Medication:
    unit = d.get("unit")
    return Medication(name=normalize_name(d["name"]), dose=d.get("dose"),
                      unit=unit.lower() if isinstance(unit, str) else None,
                      doses_per_day=d.get("doses_per_day"), route=d.get("route"),
                      prn=bool(d.get("prn", False)))


def patient_from_dict(d: dict) -> Patient:
    return Patient(
        id=str(d.get("id", "patient")), age=int(d["age"]), sex=d.get("sex"),
        egfr=d.get("egfr"), conditions=list(d.get("conditions", [])),
        allergies=list(d.get("allergies", [])),
        medications=[_med_from_dict(m) for m in d.get("medications", [])],
        home_medications=[_med_from_dict(m) for m in d.get("home_medications", [])],
        intentionally_stopped=[normalize_name(s) for s in d.get("intentionally_stopped", [])])


def load_patient(path: str) -> Patient:
    return patient_from_dict(json.loads(Path(path).read_text()))
