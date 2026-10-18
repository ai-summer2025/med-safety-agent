"""Core data models. Plain dataclasses, no third-party dependencies."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import List, Optional


class Severity(str, Enum):
    """Ordered from most to least urgent."""

    CONTRAINDICATED = "contraindicated"
    MAJOR = "major"
    MODERATE = "moderate"
    MINOR = "minor"
    INFO = "info"

    @property
    def rank(self) -> int:
        return list(Severity).index(self)


@dataclass
class Medication:
    name: str  # normalized generic name, lowercase
    dose: Optional[float] = None
    unit: Optional[str] = None  # mg, mcg, g, units, ml, meq
    doses_per_day: Optional[float] = None  # None when unknown or PRN
    route: Optional[str] = None
    prn: bool = False
    raw: Optional[str] = None  # original text, if extracted from a note

    @property
    def daily_dose_mg(self) -> Optional[float]:
        """Total scheduled daily dose in mg, when it can be computed."""
        if self.dose is None or self.doses_per_day is None or self.unit is None:
            return None
        factor = {"mg": 1.0, "g": 1000.0, "mcg": 0.001}.get(self.unit)
        if factor is None:
            return None
        return self.dose * factor * self.doses_per_day


@dataclass
class Patient:
    id: str
    age: int
    sex: Optional[str] = None
    egfr: Optional[float] = None  # mL/min/1.73m2, used as a proxy for CrCl
    conditions: List[str] = field(default_factory=list)
    allergies: List[str] = field(default_factory=list)
    medications: List[Medication] = field(default_factory=list)
    # Optional: pre-admission list, for reconciliation against `medications`
    home_medications: List[Medication] = field(default_factory=list)
    # Home meds intentionally stopped by the team (documented)
    intentionally_stopped: List[str] = field(default_factory=list)


@dataclass
class Finding:
    rule_id: str
    category: str
    severity: Severity
    drugs: List[str]
    message: str
    recommendation: str
    source: str

    @property
    def key(self) -> tuple:
        """Identity used for de-duplication and evaluation."""
        return (self.rule_id, tuple(sorted(self.drugs)))

    def to_dict(self) -> dict:
        d = asdict(self)
        d["severity"] = self.severity.value
        return d
