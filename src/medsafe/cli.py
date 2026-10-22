"""Command line interface.

  medsafe check data/patients/elderly_polypharmacy.json
  medsafe check patient.json --format json
  medsafe extract note.txt            # regex baseline
  medsafe extract note.txt --llm      # LLM extraction with grounding check
  medsafe note note.txt --age 78 --egfr 28 --llm   # extract, then check
  medsafe fhir bundle.json [--as-of latest] [--format markdown|json|detectedissue]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
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

    f = sub.add_parser("fhir", help="Check a FHIR R4 Bundle (US Core resources)")
    f.add_argument("bundle")
    f.add_argument("--as-of", default="today",
                   help="Date for age and eGFR recency: today, latest (most recent date in the bundle), or YYYY-MM-DD")
    f.add_argument("--egfr-max-age-days", type=int, default=90)
    f.add_argument("--format", choices=["markdown", "json", "detectedissue"], default="markdown")

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
    elif args.cmd == "fhir":
        return _fhir(args)
    return 0


def _routine(reason: str) -> bool:
    return reason.startswith(("status ", "condition ignored", "allergy ignored", "eGFR status"))


def _fhir(args) -> int:
    from datetime import date

    from .fhir import as_bundle, detected_issues, iter_resources, latest_clinical_date, patient_from_fhir, run_fhir
    resources = list(iter_resources(json.loads(Path(args.bundle).read_text())))
    if args.as_of == "latest":
        as_of = latest_clinical_date(resources) or date.today()
    elif args.as_of == "today":
        as_of = date.today()
    else:
        as_of = date.fromisoformat(args.as_of)
    try:
        ctx = patient_from_fhir(resources, as_of=as_of, egfr_max_age_days=args.egfr_max_age_days)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    report = run_fhir(ctx)
    if args.format == "detectedissue":
        print(json.dumps(as_bundle(detected_issues(report, ctx)), indent=2))
    elif args.format == "json":
        print(json.dumps({**report.to_dict(), "as_of": as_of.isoformat(), "egfr_used": ctx.egfr_used,
                          "sources": ctx.sources, "notes": [n.__dict__ for n in ctx.notes]}, indent=2))
    else:
        print(to_markdown(report))
        egfr = f"{ctx.egfr_used[0]} ({ctx.egfr_used[1]}, LOINC {ctx.egfr_used[2]})" if ctx.egfr_used else "none"
        print(f"\n**Data used (as of {as_of}):** age {ctx.patient.age}, {len(ctx.patient.medications)} active "
              f"medications, {len(ctx.patient.allergies)} allergy terms, {len(ctx.patient.conditions)} condition "
              f"terms, eGFR {egfr}")
        routine = Counter(n.reason.split(" (")[0] for n in ctx.notes if _routine(n.reason))
        important = [n for n in ctx.notes if not _routine(n.reason)]
        if important:
            print("\n**Needs attention (not checked or partly used):**")
            for n in important:
                print(f"- {n.resource}: {n.reason}")
        if routine:
            print("\n**Routinely skipped:** " + "; ".join(f"{k}: {v}" for k, v in sorted(routine.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
