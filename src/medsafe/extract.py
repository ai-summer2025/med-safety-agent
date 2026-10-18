"""Turn free-text medication lists into structured `Medication` objects.

Two extractors share one output format:

* `extract_rules(text)` - regex baseline. Fast, offline, deterministic.
  Handles one-medication-per-line lists ("metoprolol succinate 50 mg PO daily").
* `extract_llm(text, client)` - asks an LLM for JSON, then *verifies* every
  item against the source text. Items whose quoted evidence cannot be found
  in the note are dropped (a guard against hallucinated medications).

`eval/run_eval.py` compares the two on a labeled set of synthetic notes.
"""
from __future__ import annotations

import json
import re
from typing import List, Optional, Tuple

from .knowledge.vocab import normalize_name
from .models import Medication

FREQ_PATTERNS: List[Tuple[str, Optional[float]]] = [
    (r"\b(q\.?i\.?d|four times (a|per) day|4 times daily)\b", 4),
    (r"\b(t\.?i\.?d|three times (a|per) day|3 times daily)\b", 3),
    (r"\b(b\.?i\.?d|twice (a|per) day|twice daily|2 times daily)\b", 2),
    (r"\bq\s?4\s?h(ours)?\b|\bevery 4 hours\b", 6),
    (r"\bq\s?6\s?h(ours)?\b|\bevery 6 hours\b", 4),
    (r"\bq\s?8\s?h(ours)?\b|\bevery 8 hours\b", 3),
    (r"\bq\s?12\s?h(ours)?\b|\bevery 12 hours\b", 2),
    (r"\b(daily|once daily|once a day|q\.?d|qam|qpm|qhs|at bedtime|nightly|every morning|every evening|q24h)\b", 1),
    (r"\b(weekly|once a week)\b", 1 / 7),
]
ROUTES = {"po": "oral", "oral": "oral", "by mouth": "oral", "iv": "iv", "sq": "subcutaneous",
          "subq": "subcutaneous", "sc": "subcutaneous", "im": "im", "topical": "topical",
          "inh": "inhaled", "inhaled": "inhaled", "sl": "sublingual"}

LINE_RE = re.compile(
    r"^\s*(?:[-*•]|\d+[.)])?\s*"                      # bullet or numbering
    r"(?P<name>[A-Za-z][A-Za-z\-/ ]*?[A-Za-z])\s+"         # drug name
    r"(?P<dose>\d+(?:\.\d+)?)\s*(?P<unit>mg|mcg|g|units?|ml|meq)\b"
    r"(?P<rest>.*)$", re.IGNORECASE)

SECTION_HINT = re.compile(r"medications?|meds|discharge|home|current", re.IGNORECASE)


def parse_frequency(text: str) -> Tuple[Optional[float], bool]:
    """Return (doses_per_day, prn). PRN-only orders return (None, True)."""
    t = text.lower()
    prn = bool(re.search(r"\bprn\b|as needed", t))
    for pattern, per_day in FREQ_PATTERNS:
        if re.search(pattern, t):
            return (None if prn else per_day), prn
    return None, prn


def parse_route(text: str) -> Optional[str]:
    t = f" {text.lower()} "
    for k, v in ROUTES.items():
        if f" {k} " in t:
            return v
    return None


def extract_rules(text: str) -> List[Medication]:
    meds: List[Medication] = []
    for line in text.splitlines():
        m = LINE_RE.match(line)
        if not m:
            continue
        name = normalize_name(m.group("name"))
        unit = m.group("unit").lower()
        unit = "units" if unit.startswith("unit") else unit
        per_day, prn = parse_frequency(m.group("rest"))
        meds.append(Medication(name=name, dose=float(m.group("dose")), unit=unit,
                               doses_per_day=per_day, prn=prn,
                               route=parse_route(m.group("rest")), raw=line.strip()))
    return meds


LLM_SYSTEM = """You extract medication orders from clinical text.
Return ONLY a JSON array. Each element:
{"name": str, "dose": number|null, "unit": "mg"|"mcg"|"g"|"units"|"ml"|"meq"|null,
 "doses_per_day": number|null, "prn": bool, "route": str|null,
 "evidence": str}
Rules:
- "evidence" must be an exact substring copied from the text that mentions this medication.
- Use generic names when the text gives a brand name, but keep evidence exact.
- doses_per_day: daily=1, BID=2, TID=3, QID=4, q6h=4, q8h=3, q12h=2. PRN-only => null and prn=true.
- Include only medications the patient is currently taking or being discharged on.
  Exclude medications described as stopped, discontinued, held, or allergies.
- If there are none, return []."""


def _parse_json_array(raw: str) -> list:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        data = json.loads(raw[start:end + 1])
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def extract_llm(text: str, client) -> List[Medication]:
    """LLM extraction with an evidence-grounding check."""
    raw = client.complete(LLM_SYSTEM, text)
    meds: List[Medication] = []
    lowered = " ".join(text.lower().split())
    for item in _parse_json_array(raw):
        if not isinstance(item, dict) or not item.get("name"):
            continue
        evidence = " ".join(str(item.get("evidence", "")).lower().split())
        if not evidence or evidence not in lowered:
            continue  # ungrounded: drop rather than trust
        unit = item.get("unit")
        unit = unit.lower() if isinstance(unit, str) else None
        try:
            dose = float(item["dose"]) if item.get("dose") is not None else None
            per_day = float(item["doses_per_day"]) if item.get("doses_per_day") is not None else None
        except (TypeError, ValueError):
            dose, per_day = None, None
        meds.append(Medication(name=normalize_name(str(item["name"])), dose=dose, unit=unit,
                               doses_per_day=per_day, prn=bool(item.get("prn", False)),
                               route=item.get("route"), raw=item.get("evidence")))
    return meds
