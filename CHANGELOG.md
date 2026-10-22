# Changelog

## 1.1.0

FHIR R4 input and a CDS Hooks service.

- `medsafe.fhir`: adapter from FHIR R4 bundles (US Core shaped) to the checks, with explicit status rules,
  RxNorm code and name resolution, unit-aware dosing (tablet counts × strength, weekly timing) and eGFR recency
- `medsafe fhir` CLI command; markdown, JSON or FHIR `DetectedIssue` output
- `medsafe-cds`: CDS Hooks 2.0 `order-sign` and `patient-view` services with prefetch, FHIR fallback,
  JWT verification, suggestions, override reasons, feedback and an audit log without patient identifiers
- New duplicate class for P2Y12 inhibitors; the broad antiplatelet duplicate is dropped when a more specific
  major one covers the same drugs
- Evaluation: FHIR parity (64/64) added to `eval/RESULTS.md` and the CI regression gate
- `scripts/synthea_smoke.py`: robustness run over Synthea patients (104/104 load, 0 errors)

## 1.0.0

Consolidates eight earlier prototypes into one package.

- Single `medsafe` package with a CLI, a library API and markdown/JSON reports
- Eight deterministic checks driven by a sourced rule table (`knowledge/rules.py`)
- Free-text extraction: regex baseline plus an optional LLM extractor with an evidence-grounding check
  (Anthropic or any OpenAI-compatible server, including local models); no SDK dependencies
- Removed the dependency on the NLM RxNav interaction API, which was discontinued in January 2024
- Unknown drugs are reported as "not checked" instead of silently passing
- Evaluation harness with 32 labeled cases and 10 labeled notes; CI fails on regression
- GitHub Actions on Python 3.9-3.13, ruff, Dockerfile
