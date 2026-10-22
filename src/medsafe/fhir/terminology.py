"""Terminology: RxNorm, SNOMED CT, ICD-10-CM and LOINC as used by the FHIR adapter.

Design rules
------------
* Codes beat text. An RxNorm ingredient code maps directly through a table that was
  checked against NLM RxNav (rxnorm_ingredients.tsv, with its retrieval date).
* RxNorm clinical drug names (SCD/SBD, e.g. "Simvastatin 20 MG Oral Tablet") follow a
  documented naming convention, so ingredient and strength are parsed from the display
  when the code itself is not an ingredient code. This needs no network access, so the
  service never waits on an external terminology server while answering a hook.
* Anything that cannot be resolved is reported as unresolved, never guessed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from ..knowledge.vocab import classes_of, known_drugs, normalize_name

RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"
SNOMED = "http://snomed.info/sct"
ICD10CM = "http://hl7.org/fhir/sid/icd-10-cm"
ICD10 = "http://hl7.org/fhir/sid/icd-10"
LOINC = "http://loinc.org"
UCUM = "http://unitsofmeasure.org"


def _load_rxnorm() -> Dict[str, str]:
    table: Dict[str, str] = {}
    for line in (Path(__file__).parent / "rxnorm_ingredients.tsv").read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        rxcui, _tty, name = line.split("\t")
        table[rxcui] = name
    return table


RXCUI_TO_INGREDIENT: Dict[str, str] = _load_rxnorm()
INGREDIENT_TO_RXCUI: Dict[str, str] = {v: k for k, v in RXCUI_TO_INGREDIENT.items()}

# RxNorm ingredient names that differ from medsafe's names.
INGREDIENT_ALIASES = {
    "insulin isophane, human": "insulin nph",
    "insulin, regular, human": "insulin regular",
    "valproic acid": "valproate",
    "alendronic acid": "alendronate",
    "sennosides, usp": "senna",
    "sennosides": "senna",
}

# Multi-ingredient products that medsafe's rules treat as one drug.
COMBINATIONS = {
    frozenset({"sulfamethoxazole", "trimethoprim"}): "sulfamethoxazole-trimethoprim",
    frozenset({"amoxicillin", "clavulanate"}): "amoxicillin-clavulanate",
    frozenset({"piperacillin", "tazobactam"}): "piperacillin-tazobactam",
}

# Words that RxNorm puts in front of the ingredient name in clinical drug names.
_PREFIX = re.compile(
    r"^(?:\d+(?:\.\d+)?\s+(?:HR|ACTUAT|ML|MG|DAY)\s+|Abuse-Deterrent\s+|NDA\d+\s+|ANDA\d+\s+|BLA\d+\s+)+",
    re.I)
_PART = re.compile(
    r"^(?P<name>.+?)\s+(?P<val>\d+(?:\.\d+)?)\s*(?P<unit>MG|MCG|G|UNT|MEQ|ML|%)"
    r"(?:/(?P<per>ML|ACTUAT|HR|MG|G))?(?P<rest>(?:\s.*)?)$", re.I)
_MASS_TO_MG = {"mg": 1.0, "mcg": 0.001, "g": 1000.0}


@dataclass
class Ingredient:
    name: str  # medsafe name (lowercase generic)
    strength: Optional[float] = None
    unit: Optional[str] = None  # mg | mcg | g | unt | meq | ml | %
    per: Optional[str] = None  # ml | actuat | hr | mg, when strength is a concentration or rate
    known: bool = True  # False: not in medsafe's vocabulary, so no rule can fire on it

    @property
    def mg_per_unit(self) -> Optional[float]:
        """mg per countable unit (tablet/capsule), when strength is a plain mass."""
        if self.strength is None or self.per or (self.unit or "").lower() not in _MASS_TO_MG:
            return None
        return self.strength * _MASS_TO_MG[self.unit.lower()]


@dataclass
class ResolvedDrug:
    ingredients: List[Ingredient] = field(default_factory=list)
    dose_form: Optional[str] = None
    source: str = "unresolved"  # rxnorm-code | rxnorm-name | text | unresolved
    display: Optional[str] = None
    note: Optional[str] = None

    @property
    def countable(self) -> bool:
        return bool(self.dose_form and re.search(r"tablet|capsule", self.dose_form, re.I))


def canonical_ingredient(raw: str) -> Optional[str]:
    """Map an ingredient string to medsafe's name; strip salts only if the result is a known drug."""
    n = " ".join(raw.lower().replace("_", " ").split())
    n = INGREDIENT_ALIASES.get(n, n)
    if "," in n and n not in INGREDIENT_ALIASES:  # "nitrofurantoin, macrocrystals"
        head = canonical_ingredient(n.split(",")[0])
        if head:
            return head
    vocab = known_drugs() | set(INGREDIENT_TO_RXCUI)
    candidate = normalize_name(n)
    if candidate in vocab:
        return candidate
    words = n.split()
    for cut in range(len(words) - 1, 0, -1):  # drop trailing salt words: "naproxen sodium", "hydrocodone bitartrate"
        c = normalize_name(" ".join(words[:cut]))
        c = INGREDIENT_ALIASES.get(c, c)
        if c in vocab:
            return c
    return None


def parse_rxnorm_name(display: str) -> ResolvedDrug:
    """Parse an RxNorm SCD/SBD-style name into ingredients, strengths and dose form."""
    text = (display or "").strip()
    if not text:
        return ResolvedDrug(note="empty display")
    if text.startswith("{"):
        return ResolvedDrug(display=text, note="multi-product pack not parsed")
    text = re.sub(r"\s*\[[^\]]*\]\s*$", "", text)  # trailing [Brand]
    text = _PREFIX.sub("", text)
    parts = [p.strip() for p in text.split(" / ")]
    ingredients: List[Ingredient] = []
    form = None
    for i, part in enumerate(parts):
        m = _PART.match(part)
        if m:
            raw = m.group("name")
            if i == len(parts) - 1:
                form = m.group("rest").strip() or None
            name = canonical_ingredient(raw)
            ingredients.append(Ingredient(name or raw.lower(), float(m.group("val")), m.group("unit").lower(),
                                          (m.group("per") or "").lower() or None, known=name is not None))
        else:  # ingredient without strength, e.g. "Sulfamethoxazole / Trimethoprim"
            name = canonical_ingredient(part)
            ingredients.append(Ingredient(name or part.lower(), known=name is not None))
    unknown = [i.name for i in ingredients if not i.known]
    note = f"not in medsafe vocabulary: {', '.join(unknown)}" if unknown else None
    return ResolvedDrug(_merge_combinations(ingredients), form, "rxnorm-name", display, note)


def _merge_combinations(ings: List[Ingredient]) -> List[Ingredient]:
    names = frozenset(i.name for i in ings)
    for combo, merged in COMBINATIONS.items():
        if combo <= names:
            first = next(i for i in ings if i.name == sorted(combo)[0])
            rest = [i for i in ings if i.name not in combo]
            return [Ingredient(merged, first.strength, first.unit, first.per)] + rest
    return ings


def resolve_medication(codeable: Optional[dict]) -> ResolvedDrug:
    """Resolve a FHIR CodeableConcept for a medication."""
    if not codeable:
        return ResolvedDrug(note="no medication code")
    codings = codeable.get("coding") or []
    for c in codings:
        if c.get("system") == RXNORM and str(c.get("code")) in RXCUI_TO_INGREDIENT:
            name = canonical_ingredient(RXCUI_TO_INGREDIENT[str(c["code"])]) or RXCUI_TO_INGREDIENT[str(c["code"])]
            parsed = parse_rxnorm_name(c.get("display") or codeable.get("text") or "")
            ing = parsed.ingredients[0] if len(parsed.ingredients) == 1 else Ingredient(name)
            ing.name = name
            return ResolvedDrug([ing], parsed.dose_form, "rxnorm-code", c.get("display") or codeable.get("text"))
    for c in codings:
        if c.get("system") == RXNORM and c.get("display"):
            r = parse_rxnorm_name(c["display"])
            if any(i.known for i in r.ingredients):
                return r
    if codeable.get("text"):
        r = parse_rxnorm_name(codeable["text"])
        if any(i.known for i in r.ingredients):
            r.source = "text"
            return r
    shown = (codings[0].get("display") if codings else None) or codeable.get("text")
    return ResolvedDrug(display=shown, note="could not resolve medication code or name")


# --------------------------------------------------------------------------- conditions
# Canonical labels are the keywords medsafe's rules look for (see knowledge/rules.py).
# SNOMED codes listed here are only those seen with matching official display names in
# Synthea R4 sample data; other SNOMED codes fall back to display-text matching.
SNOMED_CONDITIONS = {
    "26929004": "dementia",  # Alzheimer's disease (disorder)
    "88805009": "heart failure",  # Chronic congestive heart failure (disorder)
    "431855005": "chronic kidney disease",  # CKD stage 1
    "431856006": "chronic kidney disease",  # CKD stage 2
    "433144002": "chronic kidney disease",  # CKD stage 3
    "431857002": "chronic kidney disease",  # CKD stage 4
    "195967001": "asthma",
    "233678006": "asthma",  # Childhood asthma
    "90560007": "gout",
    "370143000": "depression",  # Major depressive disorder
    "36923009": "depression",  # Major depression, single episode
}
ICD10_PREFIXES: List[Tuple[str, str]] = [
    ("F01", "dementia"), ("F02", "dementia"), ("F03", "dementia"), ("G30", "dementia"),
    ("I50", "heart failure"), ("N18", "chronic kidney disease"), ("J45", "asthma"),
    ("M10", "gout"), ("F32", "depression"), ("F33", "depression"),
    ("K25", "peptic ulcer disease"), ("K26", "peptic ulcer disease"), ("K27", "peptic ulcer disease"),
    ("Z91.81", "history of falls"), ("R29.6", "history of falls"),
]


def condition_labels(codeable: Optional[dict]) -> List[str]:
    """Display text plus canonical labels derived from codes."""
    if not codeable:
        return []
    labels: List[str] = []
    for c in codeable.get("coding") or []:
        if c.get("display"):
            labels.append(c["display"])
        code = str(c.get("code", ""))
        if c.get("system") == SNOMED and code in SNOMED_CONDITIONS:
            labels.append(SNOMED_CONDITIONS[code])
        if c.get("system") in (ICD10CM, ICD10):
            for prefix, label in ICD10_PREFIXES:
                if code.upper().startswith(prefix):
                    labels.append(label)
    if codeable.get("text"):
        labels.append(codeable["text"])
    return list(dict.fromkeys(labels))


# --------------------------------------------------------------------------- allergies
_CLASS_ALLERGY_KEYWORD = {
    "penicillin": "penicillin", "sulfonamide_antibiotic": "sulfa", "nsaid": "nsaid",
    "statin": "statin", "ace_inhibitor": "ace inhibitor",
}


def allergy_labels(codeable: Optional[dict]) -> List[str]:
    """Allergen text plus ingredient names and drug-class keywords derived from RxNorm codes/names."""
    if not codeable:
        return []
    labels: List[str] = []
    drug = resolve_medication(codeable)
    for ing in (i for i in drug.ingredients if i.known):
        labels.append(ing.name)
        for cls in classes_of(ing.name):
            if cls in _CLASS_ALLERGY_KEYWORD:
                labels.append(_CLASS_ALLERGY_KEYWORD[cls])
    for c in codeable.get("coding") or []:
        if c.get("display"):
            labels.append(c["display"])
    if codeable.get("text"):
        labels.append(codeable["text"])
    return list(dict.fromkeys(label.lower() for label in labels))


# --------------------------------------------------------------------------- labs
EGFR_LOINC = {
    "98979-8": "eGFR CKD-EPI 2021",
    "62238-1": "eGFR CKD-EPI",
    "33914-3": "eGFR MDRD",
    "48642-3": "eGFR MDRD (non-Black)",
    "48643-1": "eGFR MDRD (Black)",
}
EGFR_UNITS = {"mL/min/{1.73_m2}", "mL/min/1.73m2", "mL/min/1.73 m2", "mL/min"}


def codes_in(codeable: Optional[dict], system: str) -> Iterable[str]:
    for c in (codeable or {}).get("coding") or []:
        if c.get("system") == system and c.get("code"):
            yield str(c["code"])
