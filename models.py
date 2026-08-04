"""Data models for the Drug Safety Agent."""
from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum


class RiskLevel(Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass
class Medication:
    """Represents a single medication in a patient's list."""
    name: str
    rxcui: Optional[str] = None  # RxNorm Concept Unique Identifier
    generic_name: Optional[str] = None
    dose: Optional[str] = None
    frequency: Optional[str] = None

    def __repr__(self):
        return f"Medication(name={self.name!r}, dose={self.dose!r})"


@dataclass
class AdverseEvent:
    """An adverse event report from FDA FAERS."""
    drug_name: str
    reaction: str
    outcome: Optional[str] = None
    serious: bool = False
    report_count: int = 0

    def __repr__(self):
        return f"AdverseEvent(drug={self.drug_name!r}, reaction={self.reaction!r}, serious={self.serious})"


@dataclass
class DrugInteraction:
    """A drug-drug interaction from RxNav."""
    drug_a: str
    drug_b: str
    severity: str  # "N/A", "moderate", "serious", "contraindicated"
    description: str
    rxcui_a: Optional[str] = None
    rxcui_b: Optional[str] = None

    @property
    def is_serious(self) -> bool:
        return self.severity.lower() in ("serious", "contraindicated")

    def __repr__(self):
        return f"DrugInteraction({self.drug_a!r} x {self.drug_b!r}, severity={self.severity!r})"


@dataclass
class MedicationRiskProfile:
    """Risk profile for a single medication."""
    medication: Medication
    adverse_events: List[AdverseEvent] = field(default_factory=list)
    serious_event_count: int = 0
    total_event_count: int = 0
    risk_level: RiskLevel = RiskLevel.LOW
    top_reactions: List[str] = field(default_factory=list)

    def __repr__(self):
        return f"MedicationRiskProfile(med={self.medication.name!r}, risk={self.risk_level.value})"


@dataclass
class PatientSafetyReport:
    """Full safety report for a patient's medication list."""
    patient_id: str
    medications: List[Medication]
    medication_profiles: List[MedicationRiskProfile] = field(default_factory=list)
    interactions: List[DrugInteraction] = field(default_factory=list)
    overall_risk: RiskLevel = RiskLevel.LOW
    critical_alerts: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    agent_iterations: int = 0
    total_api_calls: int = 0

    def __repr__(self):
        return (f"PatientSafetyReport(patient={self.patient_id!r}, "
                f"meds={len(self.medications)}, "
                f"risk={self.overall_risk.value})")
