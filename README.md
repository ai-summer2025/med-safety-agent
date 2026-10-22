# med-safety-agent

[![CI](https://github.com/ai-summer2025/med-safety-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/ai-summer2025/med-safety-agent/actions/workflows/ci.yml)
![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

Medication safety review for care transitions. Give it a patient's medication list (structured JSON, or a free-text discharge note) and it returns the problems a pharmacist would look for: drug interactions, Beers Criteria issues in older adults, renal dosing, anticholinergic burden, allergy conflicts, dose errors, duplicates, and home-versus-discharge reconciliation gaps. Every finding names its rule and its source.

> **Decision support only.** Not a medical device and not FDA-cleared. Findings are prompts for review by a licensed clinician or pharmacist. All bundled data is synthetic.

## How it works

```
 free-text note ──► extraction ──► structured patient ──► deterministic checks ──► report
                    regex (default)                        8 checks, ~100 sourced rules    markdown / JSON
                    or LLM + grounding check
 patient JSON ─────────────────────►┘
```

The language model has one job: turning messy clinical text into a structured medication list. Every safety decision is made by deterministic, sourced rules, so the same input always produces the same findings and every finding can be traced to a label, guideline or paper.

The LLM extractor must quote the exact text supporting each medication. Items whose quote does not appear in the note are discarded, which guards against hallucinated medications.

### Why the LLM step matters

The regex baseline reads one medication per line and cannot follow sentences. On the bundled discharge summary it picks up *"Naproxen 500 mg BID was stopped on admission"* as an active order and then raises three false NSAID alerts. Telling a stopped medication from an active one is exactly what the LLM extractor is instructed to do. The evaluation below measures both.

## Checks

| Check | What it flags | Source |
|---|---|---|
| Interactions | 33 pairwise rules plus the ACEi/ARB + diuretic + NSAID "triple whammy" | FDA labels, FDA Drug Safety Communications, CredibleMeds |
| Beers Criteria | Potentially inappropriate drugs at age ≥ 65, plus disease-specific items (dementia, falls, heart failure) | 2023 AGS Beers Criteria |
| Renal dosing | Drugs to avoid or reduce below eGFR thresholds; reports the strictest applicable threshold | FDA labels, Beers 2023 |
| Anticholinergic burden | Total ACB score ≥ 3 | ACB scale (Boustani 2008; 2012 update) |
| Dose | Scheduled daily total above label maximum (with age-specific caps), daily oral methotrexate | FDA labels, FDA DSC, ISMP |
| Allergies | Direct matches and class cross-reactivity, graded (penicillin to cephalosporin is INFO, not a block) | FDA labels, 2022 drug allergy practice parameter |
| Duplicates | Same drug twice; same therapeutic class (lower severity where combinations are usually deliberate, e.g. DAPT) | Therapeutic duplication |
| Reconciliation | Home medications omitted without a documented stop (high-risk omissions escalated), dose changes, new drugs | Joint Commission NPSG.03.06.01 |

Rules live in [`src/medsafe/knowledge/rules.py`](src/medsafe/knowledge/rules.py) as plain data, one entry per rule, each with its source.

## Quickstart

```bash
pip install -e .
medsafe check data/patients/elderly_polypharmacy.json
medsafe check data/patients/discharge_reconciliation.json --format json
medsafe note data/notes/discharge_summary.txt --age 82 --egfr 31 --condition "heart failure"
```

No API key or network access is needed for these. With Docker:

```bash
docker build -t medsafe . && docker run --rm medsafe
```

Example (abridged):

```
# Medication safety review: synthetic-001
**Findings:** major: 9, moderate: 3, minor: 1

## [MAJOR] Anticoagulant with an NSAID: additive bleeding risk, including GI bleeding.
- Drugs: warfarin, naproxen
- Recommendation: Avoid if possible; use acetaminophen for pain. ...
- Rule: `DDI-ANTICOAG-NSAID` | Source: FDA-LABEL (warfarin, apixaban, rivaroxaban)
```

Use it as a library:

```python
from medsafe import load_patient, run
report = run(load_patient("data/patients/elderly_polypharmacy.json"))
for f in report.findings:
    print(f.severity.value, f.rule_id, f.drugs)
```

## Using an LLM for extraction

```bash
export ANTHROPIC_API_KEY=...                 # hosted model
medsafe note data/notes/discharge_summary.txt --age 82 --egfr 31 --llm

export LLM_PROVIDER=openai           # or any OpenAI-compatible server,
export LLM_BASE_URL=http://localhost:11434/v1   # e.g. a local Ollama model
export LLM_MODEL=llama3.1
medsafe extract data/notes/discharge_summary.txt --llm
```

For real patient data, use a local model or a provider covered by a BAA; with a hosted API the note text leaves your machine. There are no SDK dependencies: the clients in [`llm.py`](src/medsafe/llm.py) use the standard library.

## FHIR R4 and CDS Hooks

medsafe can read FHIR R4 data directly and run inside an EHR as a [CDS Hooks 2.0](https://cds-hooks.hl7.org/STU2/) service. The checks are the same; only the input and output change.

```
 EHR ── order-sign / patient-view ──► medsafe-cds ──► FHIR adapter ──► checks ──► CDS cards
        (prefetch, or FHIR reads                     (status rules,                (only the new order's
         with the hook's access token)                RxNorm, eGFR)                 problems on order-sign)
```

**What it reads** (US Core shaped): `Patient`, `MedicationRequest`, `MedicationStatement` (home list, patient-view), `AllergyIntolerance`, `Condition`, and eGFR `Observation`s (LOINC 98979-8, 62238-1, 33914-3, 48642-3, 48643-1).

**Rules applied before any check runs**, all listed in the report's "Data used" section:

- Only `active` orders with intent `order`/`plan`; `doNotPerform`, completed, stopped and entered-in-error orders are ignored
- Refuted or entered-in-error allergies and resolved or inactive conditions are ignored
- eGFR: most recent `final`/`amended`/`corrected` result within 90 days (configurable); a `<15` result counts as below 15
- Medications resolve by RxNorm code first (a 200-ingredient table verified against NLM RxNav), then by parsing the RxNorm name: `Acetaminophen 325 MG / Oxycodone Hydrochloride 10 MG Oral Tablet [Percocet]` gives two ingredients with strengths, so a tablet count becomes a mg dose
- Anything that does not resolve is reported as not checked, never silently passed

**Command line:**

```bash
medsafe fhir data/fhir/synthetic_patient_bundle.json --as-of 2026-06-01
medsafe fhir bundle.json --format detectedissue > issues.json   # FHIR DetectedIssue resources
```

**CDS Hooks service:**

```bash
pip install -e ".[service]"
MEDSAFE_TRUSTED_ISSUERS='{"https://ehr.example.org": "https://ehr.example.org/.well-known/jwks.json"}' medsafe-cds
curl localhost:8080/cds-services
```

- `medsafe-order-sign` returns cards only for problems that involve the draft order. A contraindicated or major card offers a one-click "remove draft order" suggestion and structured override reasons
- `medsafe-patient-view` reviews the whole list, including reconciliation against `MedicationStatement`s
- Lower-priority findings are folded into a single summary card, to limit alert fatigue
- Missing prefetch is fetched with the hook's `fhirAuthorization`; if the patient or medications cannot be obtained the service returns HTTP 412
- Requests must carry a JWT signed by a trusted issuer (ES/RS/PS algorithms only, `aud` = service URL, 5-minute lifetime, replay protection). `MEDSAFE_AUTH=disabled` is for local testing only
- The feedback endpoint and every issued card are written to an audit log keyed by `hookInstance`, with no patient identifiers

**How it was tested:**

- Parity: each of the 32 evaluation cases is converted to a FHIR bundle in two coding styles (ingredient codes with mg doses; product names with tablet counts). Both give findings identical to the direct input, 64/64, and CI enforces it.
- Robustness: [`scripts/synthea_smoke.py`](scripts/synthea_smoke.py) over the 104 R4 patients in [synthea-sample-data](https://github.com/synthetichealth/synthea-sample-data) loads every bundle with no errors. The only medications that do not resolve are multi-product packs (oral contraceptives), injectables and inhalers without a mg strength per unit.
- Not yet tested against a live EHR or a CDS Hooks sandbox.

## Evaluation

`python eval/run_eval.py` regenerates [`eval/RESULTS.md`](eval/RESULTS.md). CI fails if results drop below [`eval/baseline.json`](eval/baseline.json).

**Safety checks:** 32 synthetic cases, including negative controls, scored on (category, drugs) per expected finding.

| | TP | FP | FN | Precision | Recall |
|---|---|---|---|---|---|
| All checks | 44 | 0 | 2 | 1.00 | 0.96 |

The two misses are documented, real gaps: PRN doses are not counted toward daily maximums (C15), and fluoroquinolone-warfarin is not in the interaction table (C25).

Read these numbers for what they are. I wrote both the rules and the expected labels, so this measures whether the implementation does what the specification says, plus regression protection. It is **not** a clinical validation. The next step is an independent pharmacist-labeled case set.

**Medication extraction:** 10 synthetic notes with gold medication lists.

| Method | Precision | Recall | F1 | Exact dose + unit + frequency |
|---|---|---|---|---|
| Regex baseline | 0.95 | 0.67 | 0.78 | 0.67 |
| LLM + grounding | run `python eval/run_eval.py --llm` | | | |

**FHIR parity:** 64/64 (32 cases × 2 coding styles) give identical findings through the FHIR adapter.

The regex baseline fails on narrative notes (sentences, "stopped", "hold", semicolon-separated lists). The LLM row is left for you to run with your own credentials rather than reporting numbers I did not produce here.

## Limitations

- **Small vocabulary.** About 200 ingredients and 130 brand names, hand-curated, with RxNorm codes for the ingredients. Drugs outside it are listed as "not checked", never silently passed.
- **Condition coding.** SNOMED CT codes cover only the conditions seen in Synthea data; ICD-10-CM is matched by prefix, and free text is a fallback. A site using other codes needs to extend `fhir/terminology.py`.
- **Not tested in a live EHR.** The CDS Hooks service has unit tests for the protocol and security rules, but has not been run against Epic, Oracle Health or a public sandbox.
- **Curated, not comprehensive.** The interaction table covers high-yield, well-documented combinations. It is not a replacement for a commercial interaction database.
- **eGFR stands in for creatinine clearance.** Several label thresholds are defined by Cockcroft-Gault CrCl.
- **No indication or duration data.** Rules that depend on why or for how long a drug is used (e.g. PPI beyond 8 weeks, aspirin for primary prevention) are not implemented.
- **Scheduled doses only** count toward daily maximums.

## Roadmap

- Run the CDS Hooks service in a public sandbox with Synthea patients and record a demo
- Resolve SCD/SBD codes through RxNav `related.json` at build time, instead of name parsing
- Use dosage `maxDosePerPeriod` and PRN maximums in the daily-dose check
- Independent, pharmacist-labeled evaluation set
- Report LLM extraction results for a hosted and a local model

## Project history

This repository consolidates eight earlier prototypes (`drug-safety-agent`, `polypharmacy-safety-agent`, `polypharmacy-sentinel`, `med-reconcile-agent`, `med-reconciliation-agent`, `medication-reconciliation-agent`, `discharge-med-reconciler`, `discharge-med-safety-agent`) into one tested package. Several of those prototypes queried the NLM RxNav drug-interaction API, which NLM discontinued in January 2024. Some fell back to small mock tables; `drug-safety-agent` caught the failed request silently, so it would report "no interactions found" for every patient. This version uses a sourced, versioned rule table instead and never treats a lookup failure as a negative result.

See [CHANGELOG.md](CHANGELOG.md).

## References

- American Geriatrics Society Beers Criteria Update Expert Panel. 2023 Updated AGS Beers Criteria. *J Am Geriatr Soc.* 2023;71(7):2052-2081.
- Boustani M, et al. Impact of anticholinergics on the aging brain. *Aging Health.* 2008;4(3):311-320.
- Lapi F, et al. Concurrent use of diuretics, ACE inhibitors, and ARBs with NSAIDs and risk of acute kidney injury. *BMJ.* 2013;346:e8525.
- FDA Drug Safety Communications: opioids with benzodiazepines (2016), gabapentinoids with respiratory depression (2019), metformin in renal impairment (2016), citalopram dosing (2011).
- Khan DA, et al. Drug allergy: a 2022 practice parameter update. *J Allergy Clin Immunol.* 2022;150(6):1333-1393.

## License

MIT. See [LICENSE](LICENSE).
