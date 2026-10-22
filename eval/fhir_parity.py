"""Build FHIR R4 bundles from the evaluation cases, for the FHIR parity check.

Two coding styles alternate across cases, matching what EHRs send:
  * ingredient style  - RxNorm ingredient code, dose as a UCUM mass quantity (e.g. 40 mg)
  * product style     - RxNorm clinical-drug name only ("Simvastatin 40 MG Oral Tablet"),
                        dose as a unitless tablet count (Synthea style)
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from fractions import Fraction
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from medsafe.fhir.terminology import INGREDIENT_TO_RXCUI, LOINC, RXNORM  # noqa: E402
from medsafe.knowledge.vocab import normalize_name  # noqa: E402

AS_OF = date(2026, 6, 1)
COMBO_DISPLAY = {
    "sulfamethoxazole-trimethoprim": "sulfamethoxazole {d} MG / trimethoprim 160 MG Oral Tablet",
    "amoxicillin-clavulanate": "amoxicillin {d} MG / clavulanate 125 MG Oral Tablet",
}


def _timing(per_day):
    if per_day is None:
        return None
    frac = Fraction(per_day).limit_denominator(7)
    if frac.numerator == 1 and frac.denominator > 1:
        return {"repeat": {"frequency": 1, "period": frac.denominator, "periodUnit": "d"}}
    return {"repeat": {"frequency": int(per_day), "period": 1, "periodUnit": "d"}}


def _med_resource(rtype: str, rid: str, m: dict, product_style: bool, status: str) -> dict:
    name = normalize_name(m["name"])
    dose, unit = m.get("dose"), (m.get("unit") or "").lower()
    dosage: dict = {}
    timing = _timing(m.get("doses_per_day"))
    if timing:
        dosage["timing"] = timing
    if m.get("prn"):
        dosage["asNeededBoolean"] = True
    if m.get("route") == "iv":
        dosage["route"] = {"text": "Intravenous route"}
    use_product = product_style and dose is not None and unit == "mg" and m.get("route") in (None, "oral")
    if use_product:
        template = COMBO_DISPLAY.get(name, f"{name} {{d}} MG Oral Tablet")
        concept = {"coding": [{"system": RXNORM, "display": template.format(d=_num(dose))}]}
        dosage["doseAndRate"] = [{"doseQuantity": {"value": 1}}]
    else:
        coding = {"system": RXNORM, "display": name}
        if name in INGREDIENT_TO_RXCUI:
            coding["code"] = INGREDIENT_TO_RXCUI[name]
        concept = {"coding": [coding], "text": name}
        if dose is not None:
            ucum = {"mg": "mg", "mcg": "ug", "g": "g", "meq": "meq", "units": "[iU]"}.get(unit, unit)
            dosage["doseAndRate"] = [{"doseQuantity": {"value": dose, "unit": unit, "system": "http://unitsofmeasure.org",
                                                       "code": ucum}}]
    res = {"resourceType": rtype, "id": rid, "status": status, "subject": {"reference": "Patient/p"},
           "medicationCodeableConcept": concept}
    if rtype == "MedicationRequest":
        res["intent"] = "order"
        res["dosageInstruction"] = [dosage] if dosage else []
    else:
        res["dosage"] = [dosage] if dosage else []
    return res


def _num(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else str(x)


def case_to_bundle(case: dict, product_style: bool) -> dict:
    p = case["patient"]
    birth = date(AS_OF.year - p["age"], 1, 1)
    entries: List[dict] = [{"resourceType": "Patient", "id": "p", "birthDate": birth.isoformat(),
                            "gender": p.get("sex", "unknown")}]
    for i, m in enumerate(p.get("medications", [])):
        entries.append(_med_resource("MedicationRequest", f"mr{i}", m, product_style, "active"))
    for i, m in enumerate(p.get("home_medications", [])):
        entries.append(_med_resource("MedicationStatement", f"ms{i}", m, product_style, "active"))
    for i, name in enumerate(p.get("intentionally_stopped", [])):
        entries.append(_med_resource("MedicationStatement", f"stop{i}", {"name": name}, False, "stopped"))
    for i, a in enumerate(p.get("allergies", [])):
        entries.append({"resourceType": "AllergyIntolerance", "id": f"a{i}", "patient": {"reference": "Patient/p"},
                        "clinicalStatus": {"coding": [{"code": "active"}]}, "code": {"text": a}})
    for i, c in enumerate(p.get("conditions", [])):
        entries.append({"resourceType": "Condition", "id": f"c{i}", "subject": {"reference": "Patient/p"},
                        "clinicalStatus": {"coding": [{"code": "active"}]}, "code": {"text": c}})
    if p.get("egfr") is not None:
        entries.append({"resourceType": "Observation", "id": "egfr", "status": "final",
                        "code": {"coding": [{"system": LOINC, "code": "98979-8"}]},
                        "effectiveDateTime": (AS_OF - timedelta(days=10)).isoformat(),
                        "valueQuantity": {"value": p["egfr"], "unit": "mL/min/{1.73_m2}",
                                          "system": "http://unitsofmeasure.org", "code": "mL/min/{1.73_m2}"}})
    return {"resourceType": "Bundle", "type": "collection", "entry": [{"resource": r} for r in entries]}
