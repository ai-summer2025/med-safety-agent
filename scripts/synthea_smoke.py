"""Run the FHIR adapter and checks over a directory of Synthea (or other FHIR R4) patient bundles.

This is a robustness smoke test, not an accuracy evaluation: Synthea data has
no gold labels. It reports how many bundles load, how many medications resolve
to an ingredient medsafe has rules for, and which rules fire.

  python scripts/synthea_smoke.py path/to/synthea/fhir [--as-of latest] [--json out.json]

Sample data: https://github.com/synthetichealth/synthea-sample-data (R4 output).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from medsafe.fhir import iter_resources, latest_clinical_date, patient_from_fhir, run_fhir  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("directory", type=Path)
    ap.add_argument("--as-of", default="latest", help="'latest' (each record's last clinical date), 'today' or a date")
    ap.add_argument("--json", type=Path, help="write the summary as JSON")
    args = ap.parse_args()

    files = sorted(p for p in args.directory.glob("*.json")
                   if not p.name.startswith(("hospitalInformation", "practitionerInformation")))
    errors, rules, unresolved = [], Counter(), Counter()
    patients = meds = with_egfr = 0
    for path in files:
        try:
            resources = list(iter_resources(json.loads(path.read_text())))
            if args.as_of == "latest":
                as_of = latest_clinical_date(resources)
            elif args.as_of == "today":
                as_of = date.today()
            else:
                as_of = date.fromisoformat(args.as_of)
            ctx = patient_from_fhir(resources, as_of=as_of)
            report = run_fhir(ctx)
        except Exception as e:  # noqa: BLE001 - a smoke test reports every failure
            errors.append((path.name, f"{type(e).__name__}: {e}"))
            continue
        patients += 1
        meds += len(ctx.patient.medications)
        with_egfr += ctx.patient.egfr is not None
        rules.update(f.rule_id for f in report.findings)
        unresolved.update(n.reason.split("): ", 1)[1] for n in ctx.notes
                          if n.reason.startswith("medication not resolved"))

    summary = {"files": len(files), "patients": patients, "errors": errors, "active_medications": meds,
               "patients_with_recent_egfr": with_egfr, "findings_by_rule": dict(rules.most_common()),
               "unresolved_medications": dict(unresolved.most_common())}
    print(f"{patients}/{len(files)} bundles loaded, {len(errors)} errors, {meds} active medications, "
          f"{with_egfr} patients with a recent eGFR")
    print("\nFindings by rule:")
    for rule, n in rules.most_common():
        print(f"  {n:4d}  {rule}")
    print(f"\nMedications with no checkable ingredient ({len(unresolved)} distinct), top 10:")
    for item, n in unresolved.most_common(10):
        print(f"  {n:4d}  {item}")
    for name, err in errors:
        print(f"ERROR {name}: {err}", file=sys.stderr)
    if args.json:
        args.json.write_text(json.dumps(summary, indent=2) + "\n")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
