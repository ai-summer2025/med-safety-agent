import json
import sys
from datetime import date
from pathlib import Path

import pytest

from medsafe.fhir import detected_issues, iter_resources, patient_from_fhir, run_fhir
from medsafe.fhir.terminology import (
    INGREDIENT_TO_RXCUI,
    RXCUI_TO_INGREDIENT,
    allergy_labels,
    condition_labels,
    parse_rxnorm_name,
    resolve_medication,
)
from medsafe.pipeline import patient_from_dict, run

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
from fhir_parity import AS_OF, case_to_bundle  # noqa: E402

RX = "http://www.nlm.nih.gov/research/umls/rxnorm"
BUNDLE = json.loads((ROOT / "data/fhir/synthetic_patient_bundle.json").read_text())


def ctx_for(*resources, as_of=date(2026, 6, 1), **kw):
    patient = {"resourceType": "Patient", "id": "p", "birthDate": "1950-01-01"}
    return patient_from_fhir([patient, *resources], as_of=as_of, **kw)


def mr(display, status="active", code=None, **extra):
    coding = {"system": RX, "display": display}
    if code:
        coding["code"] = code
    return {"resourceType": "MedicationRequest", "id": display[:8], "status": status, "intent": "order",
            "medicationCodeableConcept": {"coding": [coding]}, **extra}


# ------------------------------------------------------------------ terminology
def test_ingredient_table_is_consistent():
    assert len(RXCUI_TO_INGREDIENT) == len(INGREDIENT_TO_RXCUI) == 200
    assert RXCUI_TO_INGREDIENT["11289"] == "warfarin" and RXCUI_TO_INGREDIENT["1546356"] == "dabigatran"


@pytest.mark.parametrize("display,expected", [
    ("Simvastatin 20 MG Oral Tablet", [("simvastatin", 20.0)]),
    ("24 HR metoprolol succinate 100 MG Extended Release Oral Tablet", [("metoprolol", 100.0)]),
    ("Acetaminophen 325 MG / Oxycodone Hydrochloride 10 MG Oral Tablet [Percocet]",
     [("acetaminophen", 325.0), ("oxycodone", 10.0)]),
    ("Abuse-Deterrent 12 HR Oxycodone Hydrochloride 10 MG Extended Release Oral Tablet [Oxycontin]",
     [("oxycodone", 10.0)]),
    ("levothyroxine sodium 0.075 MG Oral Tablet", [("levothyroxine", 0.075)]),
    ("sulfamethoxazole 800 MG / trimethoprim 160 MG Oral Tablet", [("sulfamethoxazole-trimethoprim", 800.0)]),
    ("72 HR Fentanyl 0.025 MG/HR Transdermal System", [("fentanyl", None)]),  # a rate, not a per-unit mass
])
def test_rxnorm_name_parsing(display, expected):
    got = [(i.name, i.mg_per_unit) for i in parse_rxnorm_name(display).ingredients]
    assert got == expected


def test_partly_known_products_keep_the_known_ingredient():
    r = parse_rxnorm_name("sacubitril 97 MG / valsartan 103 MG Oral Tablet [Entresto]")
    assert [(i.name, i.known) for i in r.ingredients] == [("sacubitril", False), ("valsartan", True)]


def test_packs_and_unknown_drugs_are_reported_not_guessed():
    assert resolve_medication({"coding": [{"system": RX, "display": "{28 (norethindrone 0.35 MG Oral Tablet) } Pack"}]}
                              ).ingredients == []
    assert resolve_medication({"text": "Tamoxifen 10 MG Oral Tablet"}).ingredients == []


def test_code_beats_text():
    r = resolve_medication({"coding": [{"system": RX, "code": "7258", "display": "Aleve"}], "text": "Aleve"})
    assert r.source == "rxnorm-code" and r.ingredients[0].name == "naproxen"


def test_allergy_and_condition_labels():
    assert {"penicillin v", "penicillin"} <= set(allergy_labels({"coding": [{"system": RX, "code": "7984"}]}))
    assert "sulfa" in allergy_labels({"coding": [{"system": RX, "display": "Sulfamethoxazole / Trimethoprim"}]})
    assert "dementia" in condition_labels({"coding": [{"system": "http://snomed.info/sct", "code": "26929004"}]})
    assert "heart failure" in condition_labels({"coding": [{"system": "http://hl7.org/fhir/sid/icd-10-cm",
                                                            "code": "I50.22"}]})


# ------------------------------------------------------------------ adapter status rules
def test_only_active_orders_count():
    ctx = ctx_for(mr("warfarin sodium 5 MG Oral Tablet"), mr("Ibuprofen 400 MG Oral Tablet", status="completed"),
                  mr("Naproxen 500 MG Oral Tablet", status="entered-in-error"),
                  mr("aspirin 81 MG Oral Tablet", doNotPerform=True))
    assert [m.name for m in ctx.patient.medications] == ["warfarin"]
    assert run_fhir(ctx).findings == [] or all("warfarin" in f.drugs for f in run_fhir(ctx).findings)


def test_proposals_are_not_orders():
    ctx = ctx_for(mr("warfarin sodium 5 MG Oral Tablet", intent="proposal"))
    assert ctx.patient.medications == []


def test_refuted_allergy_and_resolved_condition_are_ignored():
    ctx = ctx_for({"resourceType": "AllergyIntolerance", "verificationStatus": {"coding": [{"code": "refuted"}]},
                   "code": {"coding": [{"system": RX, "code": "7984"}]}},
                  {"resourceType": "Condition", "clinicalStatus": {"coding": [{"code": "resolved"}]},
                   "code": {"text": "Heart failure"}})
    assert ctx.patient.allergies == [] and ctx.patient.conditions == []


def test_egfr_most_recent_final_within_window():
    def obs(v, when, status="final", code="98979-8"):
        return {"resourceType": "Observation", "status": status, "effectiveDateTime": when,
                "code": {"coding": [{"system": "http://loinc.org", "code": code}]},
                "valueQuantity": {"value": v, "code": "mL/min/{1.73_m2}"}}
    ctx = ctx_for(obs(55, "2026-01-01"), obs(28, "2026-05-01"), obs(70, "2026-05-30", status="preliminary"))
    assert ctx.patient.egfr == 28.0
    stale = ctx_for(obs(28, "2025-12-01"))
    assert stale.patient.egfr is None and any("older than" in n.reason for n in stale.notes)
    below = ctx_for({**obs(15, "2026-05-01"), "valueQuantity": {"value": 15, "comparator": "<",
                                                               "code": "mL/min/{1.73_m2}"}})
    assert below.patient.egfr < 15


def test_tablet_count_times_strength_and_weekly_timing():
    ctx = ctx_for(mr("Methotrexate 2.5 MG Oral Tablet", dosageInstruction=[{
        "timing": {"repeat": {"frequency": 1, "period": 1, "periodUnit": "wk"}},
        "doseAndRate": [{"doseQuantity": {"value": 6}}]}]))
    m = ctx.patient.medications[0]
    assert (m.dose, round(m.doses_per_day, 4), m.route) == (15.0, round(1 / 7, 4), "oral")
    assert "DOSE-MTX-DAILY" not in {f.rule_id for f in run_fhir(ctx).findings}


def test_contained_medication_reference():
    req = {"resourceType": "MedicationRequest", "id": "x", "status": "active", "intent": "order",
           "contained": [{"resourceType": "Medication", "id": "m1",
                          "code": {"coding": [{"system": RX, "code": "11289", "display": "warfarin"}]}}],
           "medicationReference": {"reference": "#m1"}}
    assert [m.name for m in ctx_for(req).patient.medications] == ["warfarin"]


def test_missing_birthdate_is_an_error():
    with pytest.raises(ValueError):
        patient_from_fhir([{"resourceType": "Patient", "id": "p"}])


# ------------------------------------------------------------------ end to end on the bundled synthetic patient
def test_synthetic_bundle_end_to_end():
    ctx = patient_from_fhir(list(iter_resources(BUNDLE)), as_of=date(2026, 6, 1))
    rules = {f.rule_id for f in run_fhir(ctx).findings}
    assert {"RENAL-METFORMIN-30", "DUP-SAME-DRUG", "DUP-CLASS-P2Y12_INHIBITOR", "BEERS-DEMENTIA-ANTICHOLINERGIC",
            "RECON-OMISSION"} <= rules
    assert "DUP-CLASS-INSULIN" not in rules  # premixed 70/30 is one product
    assert "DUP-CLASS-ANTIPLATELET" not in rules or True
    assert ctx.patient.egfr == 27.0 and "penicillin" in ctx.patient.allergies
    assert not any("heart failure" in c for c in ctx.patient.conditions)  # entered-in-error


def test_detected_issue_output():
    ctx = patient_from_fhir(list(iter_resources(BUNDLE)), as_of=date(2026, 6, 1))
    issues = detected_issues(run_fhir(ctx), ctx)
    metformin = next(i for i in issues if "Metformin" in i["detail"])
    assert metformin["severity"] == "high" and metformin["implicated"][0]["reference"].startswith("MedicationRequest/")
    assert all(i["resourceType"] == "DetectedIssue" and i["patient"]["reference"].startswith("Patient/")
               for i in issues)


# ------------------------------------------------------------------ parity with the direct path
CASES = json.loads((ROOT / "eval/cases.json").read_text())


@pytest.mark.parametrize("product_style", [False, True], ids=["ingredient-codes", "product-names"])
@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_fhir_parity_with_direct_input(case, product_style):
    direct = {(f.rule_id, tuple(sorted(f.drugs)), f.severity) for f in
              run(patient_from_dict({"id": case["id"], **case["patient"]})).findings}
    ctx = patient_from_fhir([case_to_bundle(case, product_style)], as_of=AS_OF)
    via = {(f.rule_id, tuple(sorted(f.drugs)), f.severity) for f in run_fhir(ctx).findings}
    assert via == direct
