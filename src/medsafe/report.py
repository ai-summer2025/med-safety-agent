"""Human-readable rendering of a Report."""
from __future__ import annotations

from .pipeline import Report

ICON = {"contraindicated": "[CONTRAINDICATED]", "major": "[MAJOR]", "moderate": "[MODERATE]",
        "minor": "[MINOR]", "info": "[INFO]"}


def to_markdown(report: Report) -> str:
    lines = [f"# Medication safety review: {report.patient_id}", ""]
    counts = ", ".join(f"{k}: {v}" for k, v in report.counts.items() if v)
    lines.append(f"**Findings:** {counts or 'none'}")
    if report.extraction_method:
        lines.append(f"**Medication list source:** {report.extraction_method}")
    if report.unrecognized_drugs:
        lines.append("**Not in vocabulary (not checked):** " + ", ".join(report.unrecognized_drugs))
    lines.append("")
    for f in report.findings:
        lines += [f"## {ICON[f.severity.value]} {f.message}",
                  f"- Drugs: {', '.join(f.drugs)}",
                  f"- Recommendation: {f.recommendation}",
                  f"- Rule: `{f.rule_id}` | Source: {f.source}", ""]
    lines.append("_Decision support only. Findings require review by a licensed clinician or pharmacist._")
    return "\n".join(lines)

SECTION_DIV = "─" * 70
MINOR_DIV   = "· " * 35
