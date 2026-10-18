"""Command line interface.

  medsafe check data/patients/elderly_polypharmacy.json
  medsafe check patient.json --format json
  medsafe extract note.txt            # regex baseline
  medsafe extract note.txt --llm      # LLM extraction with grounding check
  medsafe note note.txt --age 78 --egfr 28 --llm   # extract, then check
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .models import Patient
from .pipeline import load_patient, medications_from_text, run
from .report import to_markdown


def _emit(report, fmt: str) -> None:
    if fmt == "json":
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(to_markdown(report))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="medsafe", description="Medication safety review (decision support).")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="Check a structured patient JSON file")
    c.add_argument("patient")
    c.add_argument("--format", choices=["markdown", "json"], default="markdown")

    e = sub.add_parser("extract", help="Extract a medication list from free text")
    e.add_argument("note")
    e.add_argument("--llm", action="store_true", help="Use an LLM (see medsafe/llm.py for config)")

    n = sub.add_parser("note", help="Extract medications from a note, then run all checks")
    n.add_argument("note")
    n.add_argument("--age", type=int, required=True)
    n.add_argument("--egfr", type=float)
    n.add_argument("--allergy", action="append", default=[])
    n.add_argument("--condition", action="append", default=[])
    n.add_argument("--llm", action="store_true")
    n.add_argument("--format", choices=["markdown", "json"], default="markdown")

    args = p.parse_args(argv)
    if args.cmd == "check":
        _emit(run(load_patient(args.patient)), args.format)
    elif args.cmd == "extract":
        meds = medications_from_text(Path(args.note).read_text(), use_llm=args.llm)
        print(json.dumps([m.__dict__ for m in meds], indent=2))
    elif args.cmd == "note":
        meds = medications_from_text(Path(args.note).read_text(), use_llm=args.llm)
        patient = Patient(id=Path(args.note).stem, age=args.age, egfr=args.egfr,
                          allergies=args.allergy, conditions=args.condition, medications=meds)
        _emit(run(patient, extraction_method="llm" if args.llm else "rules"), args.format)
    return 0


if __name__ == "__main__":
    sys.exit(main())
