import json
import subprocess
import sys
from pathlib import Path

from medsafe.cli import main

ROOT = Path(__file__).resolve().parents[1]


def test_cli_check_json(capsys):
    assert main(["check", str(ROOT / "data/patients/elderly_polypharmacy.json"), "--format", "json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["counts"]["major"] >= 1


def test_cli_note_rules(capsys, tmp_path):
    note = tmp_path / "n.txt"
    note.write_text("- warfarin 5 mg daily\n- naproxen 500 mg BID\n")
    assert main(["note", str(note), "--age", "70", "--egfr", "25"]) == 0
    out = capsys.readouterr().out
    assert "DDI-ANTICOAG-NSAID" in out and "RENAL-NSAID-30" in out


def test_eval_does_not_regress():
    r = subprocess.run([sys.executable, str(ROOT / "eval/run_eval.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
