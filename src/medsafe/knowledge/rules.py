"""Curated clinical rules.

Every rule names its source. Wording is intentionally conservative: the
tool flags a combination for a clinician or pharmacist to review; it does
not decide therapy.

Sources referenced below:
  FDA-LABEL   US prescribing information for the named drug(s) (DailyMed)
  FDA-DSC     FDA Drug Safety Communication (date given in the rule)
  BEERS-2023  2023 AGS Beers Criteria, J Am Geriatr Soc 2023;71(7):2052-2081
  ACB         Anticholinergic Cognitive Burden scale (Boustani et al., 2008; 2012 update)
  CREDIBLEMEDS  CredibleMeds QTdrugs list, "known risk of TdP" category
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ..models import Severity

S = Severity


@dataclass(frozen=True)
class PairRule:
    id: str
    a: str  # generic name or "class:<name>"
    b: str
    severity: Severity
    message: str
    recommendation: str
    source: str


INTERACTIONS: List[PairRule] = [
    PairRule("DDI-ANTICOAG-NSAID", "class:anticoagulant", "class:nsaid", S.MAJOR,
             "Anticoagulant with an NSAID: additive bleeding risk, including GI bleeding.",
             "Avoid if possible; use acetaminophen for pain. If unavoidable, add gastroprotection and monitor for bleeding.",
             "FDA-LABEL (warfarin, apixaban, rivaroxaban)"),
    PairRule("DDI-ANTICOAG-ANTIPLATELET", "class:anticoagulant", "class:antiplatelet", S.MAJOR,
             "Anticoagulant with an antiplatelet agent: additive bleeding risk.",
             "Confirm a documented indication (e.g. recent ACS/stent) and planned duration; otherwise consider stopping the antiplatelet.",
             "FDA-LABEL (warfarin, apixaban, rivaroxaban)"),
    PairRule("DDI-WARFARIN-AMIODARONE", "warfarin", "amiodarone", S.MAJOR,
             "Amiodarone inhibits warfarin metabolism and raises INR; effect can persist for weeks.",
             "Anticipate a warfarin dose reduction and check INR frequently.",
             "FDA-LABEL (warfarin, amiodarone)"),
    PairRule("DDI-WARFARIN-FLUCONAZOLE", "warfarin", "fluconazole", S.MAJOR,
             "Fluconazole inhibits warfarin metabolism and raises INR.",
             "Monitor INR closely; consider an empiric warfarin dose reduction.",
             "FDA-LABEL (warfarin)"),
    PairRule("DDI-WARFARIN-METRONIDAZOLE", "warfarin", "metronidazole", S.MAJOR,
             "Metronidazole potentiates warfarin and raises INR.",
             "Monitor INR closely or choose an alternative antibiotic.",
             "FDA-LABEL (warfarin, metronidazole)"),
    PairRule("DDI-WARFARIN-TMPSMX", "warfarin", "sulfamethoxazole-trimethoprim", S.MAJOR,
             "Sulfamethoxazole-trimethoprim potentiates warfarin and raises INR.",
             "Prefer an alternative antibiotic; if used, monitor INR closely.",
             "FDA-LABEL (warfarin)"),
    PairRule("DDI-ACEI-ARB", "class:ace_inhibitor", "class:arb", S.MAJOR,
             "Dual RAAS blockade (ACE inhibitor + ARB): higher risk of hyperkalemia, hypotension and acute kidney injury without outcome benefit.",
             "Avoid the combination; keep one agent.",
             "FDA-LABEL (ACE inhibitors, ARBs)"),
    PairRule("DDI-ACEI-KSPARING", "class:ace_inhibitor", "class:potassium_sparing_diuretic", S.MODERATE,
             "ACE inhibitor with a potassium-sparing diuretic: hyperkalemia risk.",
             "Often intentional in heart failure; check potassium and creatinine within 1 week and periodically.",
             "FDA-LABEL (spironolactone, eplerenone)"),
    PairRule("DDI-ARB-KSPARING", "class:arb", "class:potassium_sparing_diuretic", S.MODERATE,
             "ARB with a potassium-sparing diuretic: hyperkalemia risk.",
             "Often intentional in heart failure; check potassium and creatinine within 1 week and periodically.",
             "FDA-LABEL (spironolactone, eplerenone)"),
    PairRule("DDI-KSPARING-KSUPP", "class:potassium_sparing_diuretic", "class:potassium_supplement", S.MAJOR,
             "Potassium supplement with a potassium-sparing diuretic: hyperkalemia risk.",
             "Confirm the supplement is still needed; check potassium.",
             "FDA-LABEL (spironolactone, eplerenone)"),
    PairRule("DDI-SIMVA-CYP3A4", "simvastatin", "class:strong_cyp3a4_inhibitor", S.CONTRAINDICATED,
             "Strong CYP3A4 inhibitors greatly increase simvastatin levels: myopathy/rhabdomyolysis risk.",
             "Contraindicated per label. Hold simvastatin during the course or switch to a statin not dependent on CYP3A4 (e.g. pravastatin, rosuvastatin).",
             "FDA-LABEL (simvastatin)"),
    PairRule("DDI-LOVA-CYP3A4", "lovastatin", "class:strong_cyp3a4_inhibitor", S.CONTRAINDICATED,
             "Strong CYP3A4 inhibitors greatly increase lovastatin levels: myopathy/rhabdomyolysis risk.",
             "Contraindicated per label. Hold lovastatin or switch statin.",
             "FDA-LABEL (lovastatin)"),
    PairRule("DDI-SIMVA-AMIODARONE", "simvastatin", "amiodarone", S.MODERATE,
             "Amiodarone raises simvastatin exposure; label limits simvastatin to 20 mg/day with amiodarone.",
             "Keep simvastatin at or below 20 mg/day, or switch statin.",
             "FDA-LABEL (simvastatin)"),
    PairRule("DDI-MAOI-SEROTONERGIC-SSRI", "class:maoi", "class:ssri", S.CONTRAINDICATED,
             "MAOI with an SSRI: risk of serotonin syndrome.",
             "Contraindicated. Requires a washout period between agents.",
             "FDA-LABEL (SSRIs, MAOIs)"),
    PairRule("DDI-MAOI-SEROTONERGIC-SNRI", "class:maoi", "class:snri", S.CONTRAINDICATED,
             "MAOI with an SNRI: risk of serotonin syndrome.",
             "Contraindicated. Requires a washout period between agents.",
             "FDA-LABEL (SNRIs, MAOIs)"),
    PairRule("DDI-SSRI-TRAMADOL", "class:ssri", "tramadol", S.MODERATE,
             "Tramadol with an SSRI: serotonin syndrome risk and lowered seizure threshold.",
             "Consider a non-serotonergic analgesic; counsel on serotonin syndrome symptoms.",
             "FDA-LABEL (tramadol)"),
    PairRule("DDI-SNRI-TRAMADOL", "class:snri", "tramadol", S.MODERATE,
             "Tramadol with an SNRI: serotonin syndrome risk and lowered seizure threshold.",
             "Consider a non-serotonergic analgesic; counsel on serotonin syndrome symptoms.",
             "FDA-LABEL (tramadol)"),
    PairRule("DDI-SSRI-LINEZOLID", "class:ssri", "linezolid", S.MAJOR,
             "Linezolid is a reversible MAO inhibitor; with an SSRI it can cause serotonin syndrome.",
             "Avoid if alternatives exist; if necessary, monitor closely for serotonin toxicity.",
             "FDA-LABEL (linezolid)"),
    PairRule("DDI-OPIOID-BENZO", "class:opioid", "class:benzodiazepine", S.MAJOR,
             "Opioid with a benzodiazepine: risk of profound sedation, respiratory depression and death (boxed warning).",
             "Avoid co-prescribing; if unavoidable use lowest doses, shortest duration, and consider naloxone.",
             "FDA-DSC 2016-08-31 (boxed warning)"),
    PairRule("DDI-OPIOID-GABAPENTINOID", "class:opioid", "class:gabapentinoid", S.MODERATE,
             "Opioid with gabapentin/pregabalin: additive respiratory depression.",
             "Use lowest effective doses; monitor sedation, especially in older adults and renal impairment.",
             "FDA-DSC 2019-12-19"),
    PairRule("DDI-OPIOID-ZDRUG", "class:opioid", "class:z_drug", S.MAJOR,
             "Opioid with a Z-drug hypnotic: additive CNS and respiratory depression.",
             "Avoid the combination where possible.",
             "FDA-LABEL (zolpidem, eszopiclone)"),
    PairRule("DDI-CLOPIDOGREL-PPI", "clopidogrel", "omeprazole", S.MODERATE,
             "Omeprazole reduces clopidogrel's antiplatelet effect (CYP2C19 inhibition).",
             "Use pantoprazole if a PPI is needed.",
             "FDA-LABEL (clopidogrel)"),
    PairRule("DDI-CLOPIDOGREL-ESOMEPRAZOLE", "clopidogrel", "esomeprazole", S.MODERATE,
             "Esomeprazole reduces clopidogrel's antiplatelet effect (CYP2C19 inhibition).",
             "Use pantoprazole if a PPI is needed.",
             "FDA-LABEL (clopidogrel)"),
    PairRule("DDI-DIGOXIN-AMIODARONE", "digoxin", "amiodarone", S.MAJOR,
             "Amiodarone raises digoxin concentrations.",
             "Label advises reducing digoxin dose (by about half) and monitoring levels.",
             "FDA-LABEL (digoxin, amiodarone)"),
    PairRule("DDI-DIGOXIN-VERAPAMIL", "digoxin", "verapamil", S.MODERATE,
             "Verapamil raises digoxin concentrations and adds AV-nodal blockade.",
             "Monitor digoxin level and heart rate; consider digoxin dose reduction.",
             "FDA-LABEL (digoxin)"),
    PairRule("DDI-MTX-TMPSMX", "methotrexate", "sulfamethoxazole-trimethoprim", S.MAJOR,
             "Methotrexate with sulfamethoxazole-trimethoprim: risk of bone marrow suppression.",
             "Avoid; choose an alternative antibiotic.",
             "FDA-LABEL (methotrexate)"),
    PairRule("DDI-PDE5-NITRATE", "class:pde5_inhibitor", "class:nitrate", S.CONTRAINDICATED,
             "PDE5 inhibitor with a nitrate: risk of severe hypotension.",
             "Contraindicated.",
             "FDA-LABEL (sildenafil, tadalafil)"),
    PairRule("DDI-LITHIUM-ACEI", "lithium", "class:ace_inhibitor", S.MAJOR,
             "ACE inhibitors reduce lithium clearance: lithium toxicity risk.",
             "Monitor lithium levels closely or avoid.",
             "FDA-LABEL (lithium)"),
    PairRule("DDI-LITHIUM-ARB", "lithium", "class:arb", S.MAJOR,
             "ARBs reduce lithium clearance: lithium toxicity risk.",
             "Monitor lithium levels closely or avoid.",
             "FDA-LABEL (lithium)"),
    PairRule("DDI-LITHIUM-THIAZIDE", "lithium", "class:thiazide", S.MAJOR,
             "Thiazides reduce lithium clearance: lithium toxicity risk.",
             "Monitor lithium levels closely or avoid.",
             "FDA-LABEL (lithium)"),
    PairRule("DDI-LITHIUM-NSAID", "lithium", "class:nsaid", S.MAJOR,
             "NSAIDs reduce lithium clearance: lithium toxicity risk.",
             "Avoid; use acetaminophen.",
             "FDA-LABEL (lithium)"),
    PairRule("DDI-ALLOPURINOL-THIOPURINE", "allopurinol", "class:thiopurine", S.MAJOR,
             "Allopurinol blocks thiopurine metabolism: risk of severe myelosuppression.",
             "Label requires a large thiopurine dose reduction (to about one-third to one-quarter) or avoidance.",
             "FDA-LABEL (azathioprine, mercaptopurine)"),
    PairRule("DDI-QT-QT", "class:qt_prolonging", "class:qt_prolonging", S.MODERATE,
             "Two drugs with known risk of QT prolongation / torsades de pointes.",
             "Check a baseline ECG and electrolytes (K, Mg); consider an alternative to one agent.",
             "CREDIBLEMEDS"),
]

# Three-drug rule: ACEi/ARB + diuretic + NSAID ("triple whammy" AKI risk).
TRIPLE_WHAMMY_SOURCE = "Lapi et al., BMJ 2013;346:e8525"


@dataclass(frozen=True)
class BeersRule:
    id: str
    spec: str  # generic or class:
    severity: Severity
    message: str
    recommendation: str
    min_daily_mg: Optional[float] = None  # only flag above this daily dose


BEERS_SOURCE = "BEERS-2023"
BEERS_AGE = 65

BEERS: List[BeersRule] = [
    BeersRule("BEERS-ANTIHISTAMINE", "class:first_gen_antihistamine", S.MAJOR,
              "First-generation antihistamine in an older adult: strongly anticholinergic (confusion, falls, constipation, urinary retention).",
              "Avoid. For sleep or itch, consider non-anticholinergic alternatives."),
    BeersRule("BEERS-BENZO", "class:benzodiazepine", S.MAJOR,
              "Benzodiazepine in an older adult: increased risk of cognitive impairment, delirium, falls and fractures.",
              "Avoid; if long-term use, plan a gradual taper."),
    BeersRule("BEERS-ZDRUG", "class:z_drug", S.MAJOR,
              "Z-drug hypnotic in an older adult: similar fall/fracture and delirium risk to benzodiazepines with minimal benefit.",
              "Avoid; consider CBT-I or non-drug sleep measures."),
    BeersRule("BEERS-SULFONYLUREA", "class:sulfonylurea", S.MODERATE,
              "Sulfonylurea in an older adult: risk of prolonged hypoglycemia (highest with glyburide and glimepiride).",
              "Avoid as first- or second-line; if a sulfonylurea is needed, prefer short-acting glipizide."),
    BeersRule("BEERS-MUSCLE-RELAXANT", "class:muscle_relaxant", S.MODERATE,
              "Skeletal muscle relaxant in an older adult: anticholinergic effects, sedation and fall risk; poorly tolerated.",
              "Avoid."),
    BeersRule("BEERS-TCA", "class:tertiary_tca", S.MAJOR,
              "Tertiary tricyclic antidepressant in an older adult: highly anticholinergic, sedating, orthostatic hypotension.",
              "Avoid; consider an SSRI or other alternative."),
    BeersRule("BEERS-NSAID", "class:nsaid", S.MODERATE,
              "NSAID in an older adult: GI bleeding, kidney injury and heart failure exacerbation risk.",
              "Avoid chronic use unless alternatives fail and a gastroprotective agent is co-prescribed."),
    BeersRule("BEERS-DIGOXIN-DOSE", "digoxin", S.MODERATE,
              "Digoxin above 0.125 mg/day in an older adult: higher toxicity risk without added benefit.",
              "Avoid doses above 0.125 mg/day.", min_daily_mg=0.125),
    BeersRule("BEERS-WARFARIN", "warfarin", S.MINOR,
              "Warfarin started for AF/VTE in an older adult: Beers 2023 recommends a DOAC first unless contraindicated.",
              "If newly started, confirm a reason a DOAC is not suitable; if long-term and stable INR, continuing is reasonable."),
    BeersRule("BEERS-RIVAROXABAN", "rivaroxaban", S.MINOR,
              "Rivaroxaban for long-term AF/VTE in an older adult: higher major and GI bleeding than apixaban.",
              "Consider apixaban if appropriate."),
    BeersRule("BEERS-MEPERIDINE", "meperidine", S.MAJOR,
              "Meperidine in an older adult: neurotoxic metabolite, delirium risk, not an effective oral analgesic.",
              "Avoid; choose another opioid if needed."),
    BeersRule("BEERS-MEGESTROL", "megestrol", S.MODERATE,
              "Megestrol in an older adult: thrombotic risk and possible death with minimal effect on weight.",
              "Avoid."),
]

# Disease-specific Beers items: condition keyword -> (spec, message)
BEERS_CONDITION: List[Tuple[str, str, str, str]] = [
    ("BEERS-DEMENTIA-ANTICHOLINERGIC", "dementia", "class:first_gen_antihistamine",
     "Strong anticholinergic with dementia: worsens cognition."),
    ("BEERS-DEMENTIA-ANTIMUSCARINIC", "dementia", "class:bladder_antimuscarinic",
     "Bladder antimuscarinic with dementia: strongly anticholinergic, worsens cognition."),
    ("BEERS-DEMENTIA-TCA", "dementia", "class:tertiary_tca",
     "Tertiary TCA with dementia: worsens cognition."),
    ("BEERS-DEMENTIA-BENZO", "dementia", "class:benzodiazepine",
     "Benzodiazepine with dementia: worsens cognition, delirium risk."),
    ("BEERS-FALLS-BENZO", "falls", "class:benzodiazepine",
     "Benzodiazepine with a history of falls: increases fall risk."),
    ("BEERS-FALLS-ZDRUG", "falls", "class:z_drug",
     "Z-drug with a history of falls: increases fall risk."),
    ("BEERS-HF-NSAID", "heart failure", "class:nsaid",
     "NSAID with heart failure: fluid retention, can worsen heart failure."),
    ("BEERS-HF-NONDHP", "heart failure", "class:nondhp_ccb",
     "Diltiazem/verapamil with heart failure with reduced EF: negative inotropes, can worsen heart failure."),
]


@dataclass(frozen=True)
class RenalRule:
    id: str
    spec: str
    egfr_below: float
    severity: Severity
    message: str
    recommendation: str
    source: str


RENAL: List[RenalRule] = [
    RenalRule("RENAL-METFORMIN-30", "metformin", 30, S.CONTRAINDICATED,
              "Metformin with eGFR < 30: lactic acidosis risk.",
              "Contraindicated per label; stop metformin.", "FDA-DSC 2016-04-08; FDA-LABEL (metformin)"),
    RenalRule("RENAL-METFORMIN-45", "metformin", 45, S.MODERATE,
              "Metformin with eGFR 30-45: initiation not recommended; reassess benefit if already taking.",
              "Do not start at this eGFR; if continuing, consider a dose cap and monitor eGFR.", "FDA-DSC 2016-04-08"),
    RenalRule("RENAL-NSAID-30", "class:nsaid", 30, S.MAJOR,
              "NSAID with eGFR < 30: risk of further kidney injury.",
              "Avoid.", "BEERS-2023"),
    RenalRule("RENAL-NITROFURANTOIN-30", "nitrofurantoin", 30, S.MAJOR,
              "Nitrofurantoin with CrCl < 30: reduced efficacy and higher toxicity.",
              "Avoid; choose another agent.", "BEERS-2023"),
    RenalRule("RENAL-DABIGATRAN-30", "dabigatran", 30, S.MAJOR,
              "Dabigatran with CrCl < 30: increased bleeding risk.",
              "Avoid; consider an alternative anticoagulant.", "BEERS-2023; FDA-LABEL (dabigatran)"),
    RenalRule("RENAL-RIVAROXABAN-15", "rivaroxaban", 15, S.MAJOR,
              "Rivaroxaban with CrCl < 15.", "Avoid.", "BEERS-2023; FDA-LABEL (rivaroxaban)"),
    RenalRule("RENAL-RIVAROXABAN-50", "rivaroxaban", 50, S.MODERATE,
              "Rivaroxaban with CrCl 15-50: dose reduction needed for AF.",
              "Verify the dose matches the label for this renal function and indication.", "FDA-LABEL (rivaroxaban)"),
    RenalRule("RENAL-ENOXAPARIN-30", "enoxaparin", 30, S.MAJOR,
              "Enoxaparin with CrCl < 30: accumulation and bleeding risk.",
              "Use the label's reduced renal dose.", "BEERS-2023; FDA-LABEL (enoxaparin)"),
    RenalRule("RENAL-SPIRONOLACTONE-30", "spironolactone", 30, S.MAJOR,
              "Spironolactone with CrCl < 30: hyperkalemia risk.",
              "Avoid.", "BEERS-2023"),
    RenalRule("RENAL-GABAPENTINOID-60", "class:gabapentinoid", 60, S.MODERATE,
              "Gabapentin/pregabalin with CrCl < 60: accumulation causes sedation, dizziness and falls.",
              "Reduce dose per label renal dosing table.", "BEERS-2023; FDA-LABEL"),
    RenalRule("RENAL-TRAMADOL-30", "tramadol", 30, S.MODERATE,
              "Tramadol with CrCl < 30: accumulation; seizure and sedation risk.",
              "Extend dosing interval (every 12 h) and cap at 200 mg/day per label.", "BEERS-2023; FDA-LABEL (tramadol)"),
    RenalRule("RENAL-FAMOTIDINE-50", "famotidine", 50, S.MINOR,
              "Famotidine with CrCl < 50: accumulation can cause mental status changes.",
              "Reduce dose.", "BEERS-2023"),
    RenalRule("RENAL-BACLOFEN-60", "baclofen", 60, S.MAJOR,
              "Baclofen with eGFR < 60: encephalopathy risk.",
              "Avoid, or use a much lower dose with close monitoring.", "BEERS-2023"),
    RenalRule("RENAL-GLYBURIDE-60", "glyburide", 60, S.MAJOR,
              "Glyburide with reduced kidney function: active metabolites accumulate, prolonged hypoglycemia.",
              "Avoid; consider glipizide or a non-sulfonylurea agent.", "FDA-LABEL (glyburide)"),
]

# ACB scale scores. Only drugs with a published ACB score are listed.
ACB_SCORES: Dict[str, int] = {
    # score 3
    "amitriptyline": 3, "imipramine": 3, "doxepin": 3, "clomipramine": 3,
    "nortriptyline": 3, "paroxetine": 3, "diphenhydramine": 3, "hydroxyzine": 3,
    "chlorpheniramine": 3, "promethazine": 3, "oxybutynin": 3, "tolterodine": 3,
    "solifenacin": 3, "olanzapine": 3, "quetiapine": 3, "clozapine": 3,
    "benztropine": 3, "trihexyphenidyl": 3, "scopolamine": 3,
    # score 2
    "cyclobenzaprine": 2, "carbamazepine": 2, "amantadine": 2, "meperidine": 2,
    # score 1
    "alprazolam": 1, "diazepam": 1, "codeine": 1, "digoxin": 1, "furosemide": 1,
    "haloperidol": 1, "metoprolol": 1, "prednisone": 1, "trazodone": 1,
    "warfarin": 1, "risperidone": 1, "loperamide": 1,
}
ACB_THRESHOLD = 3

# Maximum labeled adult daily doses (mg/day). Conservative: flags above label max.
DOSE_MAX_MG: Dict[str, Tuple[float, str]] = {
    "acetaminophen": (4000, "FDA-LABEL (OTC acetaminophen)"),
    "ibuprofen": (3200, "FDA-LABEL (ibuprofen Rx)"),
    "naproxen": (1500, "FDA-LABEL (naproxen)"),
    "metformin": (2550, "FDA-LABEL (metformin IR)"),
    "lisinopril": (80, "FDA-LABEL (lisinopril)"),
    "losartan": (100, "FDA-LABEL (losartan)"),
    "amlodipine": (10, "FDA-LABEL (amlodipine)"),
    "atorvastatin": (80, "FDA-LABEL (atorvastatin)"),
    "simvastatin": (40, "FDA-LABEL (simvastatin; 80 mg restricted to long-term users)"),
    "rosuvastatin": (40, "FDA-LABEL (rosuvastatin)"),
    "sertraline": (200, "FDA-LABEL (sertraline)"),
    "citalopram": (40, "FDA-DSC 2011-08-24 (citalopram)"),
    "escitalopram": (20, "FDA-LABEL (escitalopram)"),
    "gabapentin": (3600, "FDA-LABEL (gabapentin)"),
    "pregabalin": (600, "FDA-LABEL (pregabalin)"),
    "tramadol": (400, "FDA-LABEL (tramadol IR)"),
    "allopurinol": (800, "FDA-LABEL (allopurinol)"),
    "hydrochlorothiazide": (50, "FDA-LABEL (hydrochlorothiazide, hypertension)"),
}
# Age-specific lower caps: drug -> (age_at_least, max_mg, source)
DOSE_MAX_BY_AGE: Dict[str, Tuple[int, float, str]] = {
    "citalopram": (61, 20, "FDA-DSC 2011-08-24 (citalopram >60 years)"),
    "tramadol": (76, 300, "FDA-LABEL (tramadol, >75 years)"),
}

# Allergy cross-reactivity. allergy keyword -> list of (spec, severity, message)
ALLERGY: Dict[str, List[Tuple[str, Severity, str]]] = {
    "penicillin": [
        ("class:penicillin", S.CONTRAINDICATED, "Penicillin-class drug ordered for a patient with a documented penicillin allergy."),
        ("class:cephalosporin", S.INFO, "Cephalosporin with penicillin allergy: cross-reactivity is low (~1-2%); clarify the reaction history."),
        ("class:carbapenem", S.INFO, "Carbapenem with penicillin allergy: cross-reactivity < 1%; clarify the reaction history."),
    ],
    "sulfa": [
        ("class:sulfonamide_antibiotic", S.CONTRAINDICATED, "Sulfonamide antibiotic ordered for a patient with a documented sulfa allergy."),
    ],
    "nsaid": [
        ("class:nsaid", S.MAJOR, "NSAID ordered for a patient with a documented NSAID allergy."),
    ],
    "aspirin": [
        ("aspirin", S.CONTRAINDICATED, "Aspirin ordered for a patient with a documented aspirin allergy."),
        ("class:nsaid", S.MAJOR, "NSAID with aspirin allergy: cross-reactivity is common in aspirin-exacerbated respiratory disease."),
    ],
    "statin": [
        ("class:statin", S.MAJOR, "Statin ordered for a patient with a documented statin intolerance/allergy."),
    ],
    "ace inhibitor": [
        ("class:ace_inhibitor", S.CONTRAINDICATED, "ACE inhibitor with documented ACE-inhibitor allergy (e.g. angioedema)."),
    ],
}
ALLERGY_SOURCE = "Drug-allergy and cross-reactivity guidance (FDA-LABEL; AAAAI/ACAAI drug allergy practice parameter 2022)"

# Home meds whose unintended omission at transition is high risk
HIGH_RISK_OMISSION_CLASSES = {"anticoagulant", "insulin", "antiepileptic"}
HIGH_RISK_OMISSION_DRUGS = {"levothyroxine", "clopidogrel", "prasugrel", "ticagrelor"}

# BEERS 2023 criteria alignment: rules flagged with beers=True correspond to
# medications the American Geriatrics Society identifies as potentially inappropriate
# in adults >= 65 years. The agent raises a BEERS warning when patient age >= 65
# and a listed drug is detected, independent of the interaction severity tier.
