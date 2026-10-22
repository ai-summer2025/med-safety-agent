"""Drug vocabulary: brand-to-generic names and therapeutic classes.

This is a deliberately small, hand-curated vocabulary covering common
inpatient and discharge medications. It is not a substitute for RxNorm.
Unknown drugs pass through unchanged; checks simply have nothing to say
about them (see README, "Limitations").
"""
from __future__ import annotations

from typing import Dict, FrozenSet, Set

BRAND_TO_GENERIC: Dict[str, str] = {
    "advil": "ibuprofen", "motrin": "ibuprofen", "aleve": "naproxen",
    "tylenol": "acetaminophen", "paracetamol": "acetaminophen",
    "coumadin": "warfarin", "jantoven": "warfarin", "eliquis": "apixaban",
    "xarelto": "rivaroxaban", "pradaxa": "dabigatran", "lovenox": "enoxaparin",
    "plavix": "clopidogrel", "brilinta": "ticagrelor", "effient": "prasugrel",
    "lasix": "furosemide", "bumex": "bumetanide", "demadex": "torsemide",
    "aldactone": "spironolactone", "inspra": "eplerenone",
    "microzide": "hydrochlorothiazide", "hctz": "hydrochlorothiazide",
    "zestril": "lisinopril", "prinivil": "lisinopril", "vasotec": "enalapril",
    "altace": "ramipril", "cozaar": "losartan", "diovan": "valsartan",
    "norvasc": "amlodipine", "cardizem": "diltiazem", "calan": "verapamil",
    "toprol xl": "metoprolol", "toprol-xl": "metoprolol", "lopressor": "metoprolol",
    "coreg": "carvedilol", "tenormin": "atenolol",
    "lipitor": "atorvastatin", "zocor": "simvastatin", "crestor": "rosuvastatin",
    "mevacor": "lovastatin", "pravachol": "pravastatin",
    "glucophage": "metformin", "glucotrol": "glipizide", "diabeta": "glyburide",
    "micronase": "glyburide", "amaryl": "glimepiride",
    "lantus": "insulin glargine", "humalog": "insulin lispro", "novolog": "insulin aspart",
    "prilosec": "omeprazole", "nexium": "esomeprazole", "protonix": "pantoprazole",
    "pepcid": "famotidine",
    "zoloft": "sertraline", "celexa": "citalopram", "lexapro": "escitalopram",
    "prozac": "fluoxetine", "paxil": "paroxetine", "effexor": "venlafaxine",
    "cymbalta": "duloxetine", "elavil": "amitriptyline", "desyrel": "trazodone",
    "nardil": "phenelzine", "parnate": "tranylcypromine",
    "xanax": "alprazolam", "ativan": "lorazepam", "valium": "diazepam",
    "klonopin": "clonazepam", "restoril": "temazepam", "ambien": "zolpidem",
    "lunesta": "eszopiclone",
    "benadryl": "diphenhydramine", "vistaril": "hydroxyzine", "atarax": "hydroxyzine",
    "phenergan": "promethazine",
    "flexeril": "cyclobenzaprine", "robaxin": "methocarbamol", "soma": "carisoprodol",
    "lioresal": "baclofen",
    "neurontin": "gabapentin", "lyrica": "pregabalin",
    "ultram": "tramadol", "oxycontin": "oxycodone", "roxicodone": "oxycodone",
    "dilaudid": "hydromorphone", "demerol": "meperidine",
    "cordarone": "amiodarone", "pacerone": "amiodarone", "lanoxin": "digoxin",
    "betapace": "sotalol",
    "synthroid": "levothyroxine", "levoxyl": "levothyroxine",
    "bactrim": "sulfamethoxazole-trimethoprim", "septra": "sulfamethoxazole-trimethoprim",
    "tmp-smx": "sulfamethoxazole-trimethoprim",
    "cipro": "ciprofloxacin", "levaquin": "levofloxacin", "avelox": "moxifloxacin",
    "zithromax": "azithromycin", "biaxin": "clarithromycin",
    "diflucan": "fluconazole", "sporanox": "itraconazole", "flagyl": "metronidazole",
    "macrobid": "nitrofurantoin", "macrodantin": "nitrofurantoin",
    "zyvox": "linezolid", "keflex": "cephalexin", "rocephin": "ceftriaxone",
    "augmentin": "amoxicillin-clavulanate",
    "zofran": "ondansetron", "haldol": "haloperidol", "seroquel": "quetiapine",
    "zyprexa": "olanzapine", "risperdal": "risperidone",
    "ditropan": "oxybutynin", "detrol": "tolterodine", "vesicare": "solifenacin",
    "viagra": "sildenafil", "revatio": "sildenafil", "cialis": "tadalafil",
    "imdur": "isosorbide mononitrate", "isordil": "isosorbide dinitrate",
    "nitrostat": "nitroglycerin",
    "zyloprim": "allopurinol", "imuran": "azathioprine", "purinethol": "mercaptopurine",
    "lithobid": "lithium", "trexall": "methotrexate",
    "k-dur": "potassium chloride", "klor-con": "potassium chloride",
    "megace": "megestrol",
}

# class -> members. A drug may belong to several classes.
CLASSES: Dict[str, FrozenSet[str]] = {k: frozenset(v) for k, v in {
    "anticoagulant": ["warfarin", "apixaban", "rivaroxaban", "dabigatran", "edoxaban",
                      "enoxaparin", "heparin"],
    "antiplatelet": ["aspirin", "clopidogrel", "prasugrel", "ticagrelor"],
    # Aspirin + one P2Y12 inhibitor is usual dual antiplatelet therapy; two P2Y12 inhibitors is not.
    "p2y12_inhibitor": ["clopidogrel", "prasugrel", "ticagrelor"],
    "nsaid": ["ibuprofen", "naproxen", "diclofenac", "celecoxib", "meloxicam",
              "indomethacin", "ketorolac"],
    "ace_inhibitor": ["lisinopril", "enalapril", "ramipril", "captopril", "benazepril",
                      "quinapril"],
    "arb": ["losartan", "valsartan", "irbesartan", "olmesartan", "candesartan",
            "telmisartan"],
    "potassium_sparing_diuretic": ["spironolactone", "eplerenone", "amiloride",
                                   "triamterene"],
    "potassium_supplement": ["potassium chloride"],
    "thiazide": ["hydrochlorothiazide", "chlorthalidone"],
    "loop_diuretic": ["furosemide", "torsemide", "bumetanide"],
    "statin": ["atorvastatin", "simvastatin", "rosuvastatin", "pravastatin", "lovastatin"],
    "strong_cyp3a4_inhibitor": ["clarithromycin", "itraconazole", "ketoconazole",
                                "posaconazole", "voriconazole", "ritonavir"],
    "ssri": ["sertraline", "fluoxetine", "citalopram", "escitalopram", "paroxetine"],
    "snri": ["venlafaxine", "duloxetine", "desvenlafaxine"],
    "maoi": ["phenelzine", "tranylcypromine", "isocarboxazid", "selegiline"],
    "opioid": ["oxycodone", "hydrocodone", "morphine", "codeine", "tramadol",
               "hydromorphone", "fentanyl", "methadone", "meperidine"],
    "benzodiazepine": ["alprazolam", "lorazepam", "diazepam", "clonazepam", "temazepam",
                       "midazolam"],
    "z_drug": ["zolpidem", "eszopiclone", "zaleplon"],
    "gabapentinoid": ["gabapentin", "pregabalin"],
    "ppi": ["omeprazole", "esomeprazole", "pantoprazole", "lansoprazole"],
    # Known-risk QT prolongers (subset of CredibleMeds "known risk of TdP")
    "qt_prolonging": ["amiodarone", "sotalol", "citalopram", "escitalopram",
                      "haloperidol", "ondansetron", "azithromycin", "clarithromycin",
                      "levofloxacin", "moxifloxacin", "ciprofloxacin", "methadone"],
    "pde5_inhibitor": ["sildenafil", "tadalafil", "vardenafil"],
    "nitrate": ["nitroglycerin", "isosorbide mononitrate", "isosorbide dinitrate"],
    "sulfonylurea": ["glipizide", "glyburide", "glimepiride"],
    "first_gen_antihistamine": ["diphenhydramine", "hydroxyzine", "chlorpheniramine",
                                "promethazine"],
    "muscle_relaxant": ["cyclobenzaprine", "methocarbamol", "carisoprodol", "metaxalone"],
    "tertiary_tca": ["amitriptyline", "imipramine", "doxepin", "clomipramine"],
    "bladder_antimuscarinic": ["oxybutynin", "tolterodine", "solifenacin", "trospium",
                               "darifenacin", "fesoterodine"],
    "beta_blocker": ["metoprolol", "carvedilol", "atenolol", "bisoprolol", "propranolol",
                     "labetalol"],
    "nondhp_ccb": ["diltiazem", "verapamil"],
    "penicillin": ["penicillin", "penicillin g", "penicillin v", "amoxicillin", "amoxicillin-clavulanate",
                   "ampicillin", "piperacillin-tazobactam", "dicloxacillin"],
    "cephalosporin": ["cephalexin", "cefazolin", "ceftriaxone", "cefuroxime", "cefepime", "cefdinir"],
    "carbapenem": ["meropenem", "imipenem", "ertapenem"],
    "fluoroquinolone": ["ciprofloxacin", "levofloxacin", "moxifloxacin"],
    "sulfonamide_antibiotic": ["sulfamethoxazole-trimethoprim"],
    "thiopurine": ["azathioprine", "mercaptopurine"],
    "insulin": ["insulin glargine", "insulin lispro", "insulin aspart", "insulin regular",
                "insulin nph"],
    "antiepileptic": ["levetiracetam", "phenytoin", "valproate", "carbamazepine",
                      "lamotrigine", "lacosamide"],
}.items()}

# Classes whose members are commonly co-prescribed on purpose; duplicates
# in these classes are reported at a lower severity ("verify intent").
INTENTIONAL_COMBINATION_CLASSES: Set[str] = {"antiplatelet", "insulin", "antiepileptic"}

# Classes too broad for the "same-class duplicate" check.
NOT_DUPLICATE_CLASSES: Set[str] = {"qt_prolonging", "strong_cyp3a4_inhibitor"}


def normalize_name(name: str) -> str:
    """Lowercase, strip salts/formulation words, map brand names to generics."""
    n = " ".join(name.lower().replace("_", " ").split())
    if n in BRAND_TO_GENERIC:
        return BRAND_TO_GENERIC[n]
    suffixes = (" succinate", " tartrate", " er", " xl", " sr", " hcl", " sodium",
                " potassium", " calcium", " hydrochloride", " dr", " extended release")
    changed = True
    while changed and n != "potassium chloride":
        changed = False
        for suffix in suffixes:
            if n.endswith(suffix) and len(n) > len(suffix):
                n = n[: -len(suffix)].strip()
                changed = True
    return BRAND_TO_GENERIC.get(n, n)


def classes_of(drug: str) -> Set[str]:
    return {cls for cls, members in CLASSES.items() if drug in members}


def matches(drug: str, spec: str) -> bool:
    """`spec` is either a generic name or `class:<name>`."""
    if spec.startswith("class:"):
        return drug in CLASSES[spec[6:]]
    return drug == spec


def known_drugs() -> Set[str]:
    drugs: Set[str] = set(BRAND_TO_GENERIC.values())
    for members in CLASSES.values():
        drugs |= members
    return drugs
