# Drug Safety Agent

An agentic AI system for medication safety analysis that autonomously queries multiple public health APIs, cross-checks drug-drug interactions, and generates risk-tiered patient safety reports.

## Overview

The Drug Safety Agent implements a multi-step agentic loop that:

1. **Resolves drug identities** via NIH RxNorm (exact + approximate matching)
2. **Queries FDA FAERS** adverse event database for each medication
3. **Checks drug-drug interactions** via NIH RxNav API for all medication pairs
4. **Scores risks** using a tiered model (LOW → MEDIUM → HIGH → CRITICAL)
5. **Validates findings** with an additional iteration for CRITICAL cases
6. **Generates reports** with actionable clinical recommendations

## Agentic Features

- **Adaptive re-querying**: If FDA results are sparse for a brand name (< 50 reports), the agent automatically retries with the generic name
- **Multi-step validation**: CRITICAL risk findings trigger a second agentic pass to confirm
- **Iterative loop**: Up to 3 agent iterations with full audit trail of API calls
- **Pairwise interaction checking**: Evaluates all drug combinations (N × (N-1) / 2 pairs)

## Free Public APIs Used

| API | Purpose | Key Required |
|-----|---------|-------------|
| FDA openFDA FAERS | Adverse event reports | None |
| NIH RxNav Drug Interactions | Drug-drug interactions | None |
| NIH RxNorm | Drug name → RxCUI resolution | None |

## Installation

```bash
pip install -r requirements.txt
```

## Usage

### Demo mode (two pre-built patient profiles)
```bash
python main.py --demo
```

### Custom medication list
```bash
python main.py --medications warfarin aspirin metformin
```

### With verbose logging
```bash
python main.py --demo --verbose
```

## Running Tests

```bash
pytest test_agent.py -v
```

Tests use mock API responses — no network access required.

## Risk Levels

| Level | Description |
|-------|-------------|
| 🟢 LOW | Routine monitoring appropriate |
| 🟡 MEDIUM | Enhanced monitoring recommended |
| 🟠 HIGH | Clinical review strongly recommended |
| 🔴 CRITICAL | Immediate clinical intervention warranted |

## Project Structure

```
drug-safety-agent/
├── models.py          # Data models (Medication, DrugInteraction, PatientSafetyReport)
├── fda_client.py      # FDA openFDA FAERS API client
├── rxnav_client.py    # NIH RxNav drug interaction API client
├── scorer.py          # Risk scoring engine
├── agent.py           # Main agentic loop
├── report.py          # Report formatting and serialization
├── main.py            # CLI entry point
└── test_agent.py      # Comprehensive pytest test suite (50+ tests)
```

## Demo Patient Profiles

**DEMO-001** — Multi-comorbidity patient:
- Warfarin 5mg + Aspirin 81mg + Metformin 500mg + Lisinopril 10mg + Atorvastatin 20mg
- Expected: HIGH or CRITICAL risk (warfarin-aspirin bleeding interaction)

**DEMO-002** — Psychiatric + pain management:
- Sertraline 100mg + Tramadol 50mg + Ibuprofen 400mg
- Expected: CRITICAL risk (serotonin syndrome warning for sertraline + tramadol)
