import json

from medsafe.extract import extract_llm, extract_rules, parse_frequency


class FakeClient:
    """Stands in for an LLM so tests run offline and deterministically."""

    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def complete(self, system, user):
        self.calls.append((system, user))
        return self.reply


def test_frequency_parsing():
    assert parse_frequency("PO BID") == (2, False)
    assert parse_frequency("every 6 hours") == (4, False)
    assert parse_frequency("q6h prn pain") == (None, True)
    assert parse_frequency("at bedtime") == (1, False)
    assert parse_frequency("once weekly")[0] == 1 / 7


def test_rules_extractor_handles_lists_and_brands():
    meds = extract_rules("1. Eliquis 5 mg PO twice daily\n- Synthroid 88 mcg daily\nNotes: none")
    assert [(m.name, m.dose, m.unit, m.doses_per_day) for m in meds] == [
        ("apixaban", 5.0, "mg", 2), ("levothyroxine", 88.0, "mcg", 1)]


def test_llm_extractor_keeps_grounded_items_and_drops_hallucinations():
    note = "Continue metformin 1000 mg twice daily. Ibuprofen was discontinued."
    reply = json.dumps([
        {"name": "metformin", "dose": 1000, "unit": "mg", "doses_per_day": 2, "prn": False,
         "evidence": "metformin 1000 mg twice daily"},
        {"name": "lisinopril", "dose": 10, "unit": "mg", "doses_per_day": 1, "prn": False,
         "evidence": "lisinopril 10 mg daily"},  # not in the note
    ])
    meds = extract_llm(note, FakeClient(reply))
    assert [m.name for m in meds] == ["metformin"]


def test_llm_extractor_tolerates_code_fences_and_bad_json():
    item = {"name": "Lasix", "dose": 40, "unit": "mg", "doses_per_day": 1, "evidence": "Lasix 40 mg"}
    good = "```json\n" + json.dumps([item]) + "\n```"
    assert extract_llm("Lasix 40 mg daily", FakeClient(good))[0].name == "furosemide"
    assert extract_llm("Lasix 40 mg daily", FakeClient("sorry, I can't")) == []
