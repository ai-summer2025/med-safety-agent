from medsafe import Medication, Patient, Severity, run
from medsafe.checks import (
    check_allergies,
    check_anticholinergic_burden,
    check_beers,
    check_doses,
    check_duplicates,
    check_interactions,
    check_reconciliation,
    check_renal,
)


def med(name, dose=None, unit="mg", per_day=1, **kw):
    from medsafe.knowledge.vocab import normalize_name
    return Medication(name=normalize_name(name), dose=dose, unit=unit, doses_per_day=per_day, **kw)


def ids(findings):
    return {f.rule_id for f in findings}


def test_brand_names_are_normalized():
    p = Patient("p", 50, medications=[med("Coumadin", 5), med("Advil", 400, per_day=3)])
    assert "DDI-ANTICOAG-NSAID" in ids(check_interactions(p))


def test_interaction_is_order_independent():
    a = Patient("a", 50, medications=[med("warfarin"), med("amiodarone")])
    b = Patient("b", 50, medications=[med("amiodarone"), med("warfarin")])
    assert ids(check_interactions(a)) == ids(check_interactions(b)) == {"DDI-WARFARIN-AMIODARONE"}


def test_contraindicated_statin_combo():
    p = Patient("p", 50, medications=[med("simvastatin", 40), med("itraconazole", 200)])
    f = check_interactions(p)
    assert f[0].severity is Severity.CONTRAINDICATED


def test_triple_whammy():
    p = Patient("p", 60, medications=[med("losartan"), med("hydrochlorothiazide"), med("naproxen")])
    assert "DDI-TRIPLE-WHAMMY" in ids(check_interactions(p))


def test_single_qt_drug_does_not_fire():
    p = Patient("p", 50, medications=[med("ondansetron", 4, per_day=3)])
    assert check_interactions(p) == []


def test_beers_only_for_65_plus():
    young = Patient("y", 64, medications=[med("lorazepam", 1)])
    old = Patient("o", 65, medications=[med("lorazepam", 1)])
    assert check_beers(young) == []
    assert "BEERS-BENZO" in ids(check_beers(old))


def test_beers_digoxin_dose_threshold():
    low = Patient("l", 80, medications=[med("digoxin", 0.125)])
    high = Patient("h", 80, medications=[med("digoxin", 0.25)])
    assert check_beers(low) == []
    assert "BEERS-DIGOXIN-DOSE" in ids(check_beers(high))


def test_renal_reports_strictest_threshold_once():
    p = Patient("p", 60, egfr=25, medications=[med("metformin", 500, per_day=2)])
    f = check_renal(p)
    assert len(f) == 1 and f[0].rule_id == "RENAL-METFORMIN-30"
    assert f[0].severity is Severity.CONTRAINDICATED


def test_renal_skipped_without_egfr():
    assert check_renal(Patient("p", 60, medications=[med("metformin")])) == []


def test_anticholinergic_burden_threshold():
    p = Patient("p", 70, medications=[med("oxybutynin", 5, per_day=2)])
    f = check_anticholinergic_burden(p)
    assert f and f[0].severity is Severity.MAJOR
    assert check_anticholinergic_burden(Patient("q", 70, medications=[med("furosemide")])) == []


def test_dose_age_specific_cap():
    assert check_doses(Patient("a", 55, medications=[med("citalopram", 40)])) == []
    assert ids(check_doses(Patient("b", 61, medications=[med("citalopram", 40)]))) == {"DOSE-ABOVE-MAX"}


def test_dose_sums_duplicate_orders():
    p = Patient("p", 40, medications=[med("acetaminophen", 1000, per_day=3), med("tylenol", 650, per_day=2)])
    assert "DOSE-ABOVE-MAX" in ids(check_doses(p))


def test_daily_methotrexate_flagged_weekly_not():
    daily = Patient("d", 50, medications=[med("methotrexate", 10, route="oral")])
    weekly = Patient("w", 50, medications=[med("methotrexate", 15, per_day=1 / 7, route="oral")])
    assert "DOSE-MTX-DAILY" in ids(check_doses(daily))
    assert check_doses(weekly) == []


def test_allergy_cross_reactivity_levels():
    p = Patient("p", 40, allergies=["Penicillin"], medications=[med("amoxicillin"), med("ceftriaxone", 1, "g")])
    sev = {f.drugs[0]: f.severity for f in check_allergies(p)}
    assert sev["amoxicillin"] is Severity.CONTRAINDICATED
    assert sev["ceftriaxone"] is Severity.INFO


def test_sulfa_allergy_does_not_flag_furosemide():
    p = Patient("p", 40, allergies=["sulfa"], medications=[med("furosemide", 40)])
    assert check_allergies(p) == []


def test_duplicates_intentional_classes_are_minor():
    p = Patient("p", 60, medications=[med("aspirin", 81), med("clopidogrel", 75)])
    f = check_duplicates(p)
    assert f[0].severity is Severity.MINOR


def test_reconciliation_omission_and_documented_stop():
    p = Patient("p", 70, medications=[med("metoprolol", 50, per_day=2)],
                home_medications=[med("warfarin", 5), med("metoprolol", 25, per_day=2), med("ibuprofen", 400)],
                intentionally_stopped=["ibuprofen"])
    f = {fi.rule_id: fi for fi in check_reconciliation(p)}
    assert f["RECON-OMISSION"].drugs == ["warfarin"] and f["RECON-OMISSION"].severity is Severity.MAJOR
    assert "RECON-DOSE-CHANGE" in f
    assert all("ibuprofen" not in fi.drugs for fi in f.values())


def test_report_sorted_by_severity_and_flags_unknown_drugs():
    p = Patient("p", 80, medications=[med("warfarin", 5), med("ibuprofen", 400, per_day=3), med("madeupzol", 5)])
    r = run(p)
    ranks = [f.severity.rank for f in r.findings]
    assert ranks == sorted(ranks)
    assert r.unrecognized_drugs == ["madeupzol"]
