#!/usr/bin/env python3
"""
Drug Safety Agent — CLI Entry Point.

Usage:
  python main.py --patient-id PT001 --medications warfarin aspirin metformin

  Or use built-in demo profiles:
  python main.py --demo
"""
import argparse
import logging
import sys

from models import Medication
from agent import DrugSafetyAgent
from report import format_report


# Demo patient profiles with realistic medication lists
DEMO_PATIENTS = [
    {
        "patient_id": "DEMO-001",
        "description": "Elderly patient with multiple comorbidities",
        "medications": [
            Medication(name="warfarin", dose="5mg", frequency="daily", generic_name="warfarin"),
            Medication(name="aspirin", dose="81mg", frequency="daily", generic_name="aspirin"),
            Medication(name="metformin", dose="500mg", frequency="twice daily", generic_name="metformin"),
            Medication(name="lisinopril", dose="10mg", frequency="daily", generic_name="lisinopril"),
            Medication(name="atorvastatin", dose="20mg", frequency="daily", generic_name="atorvastatin"),
        ],
    },
    {
        "patient_id": "DEMO-002",
        "description": "Patient on psychiatric and pain medications",
        "medications": [
            Medication(name="sertraline", dose="100mg", frequency="daily", generic_name="sertraline"),
            Medication(name="tramadol", dose="50mg", frequency="as needed", generic_name="tramadol"),
            Medication(name="ibuprofen", dose="400mg", frequency="three times daily", generic_name="ibuprofen"),
        ],
    },
]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Drug Safety Agent — Autonomous medication safety evaluation"
    )
    parser.add_argument(
        "--patient-id", default="PT-001",
        help="Patient identifier"
    )
    parser.add_argument(
        "--medications", nargs="+",
        help="Space-separated medication names"
    )
    parser.add_argument(
        "--demo", action="store_true",
        help="Run with demo patient profiles"
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Enable verbose logging"
    )
    return parser.parse_args()


def main():
    args = parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    agent = DrugSafetyAgent()

    if args.demo:
        for patient in DEMO_PATIENTS:
            print(f"\n{'='*72}")
            print(f"  Running demo: {patient['description']}")
            print(f"{'='*72}\n")
            report = agent.evaluate(
                patient_id=patient["patient_id"],
                medications=patient["medications"],
            )
            print(format_report(report))
        return

    if not args.medications:
        print("Error: Please provide --medications or use --demo")
        sys.exit(1)

    medications = [Medication(name=name) for name in args.medications]
    report = agent.evaluate(patient_id=args.patient_id, medications=medications)
    print(format_report(report))


if __name__ == "__main__":
    main()
