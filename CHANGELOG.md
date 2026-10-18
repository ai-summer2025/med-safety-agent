# Changelog

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
