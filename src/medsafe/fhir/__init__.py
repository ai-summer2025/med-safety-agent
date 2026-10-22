"""FHIR R4 support: terminology, input adapter and DetectedIssue output."""
from .adapter import FhirContext, iter_resources, latest_clinical_date, patient_from_fhir
from .output import as_bundle, detected_issues, run_fhir

__all__ = ["FhirContext", "as_bundle", "detected_issues", "iter_resources", "latest_clinical_date",
           "patient_from_fhir", "run_fhir"]
