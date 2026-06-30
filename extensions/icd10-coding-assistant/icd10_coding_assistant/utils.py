"""Shared utility functions for the ICD-10 coding assistant plugin."""

from canvas_sdk.commands.constants import CodeSystems
from canvas_sdk.v1.data.condition import Condition


def get_conditions_missing_icd10(patient_id: str) -> list[Condition]:
    """
    Get all active, non-surgical conditions for the patient that are missing ICD-10 codes.

    Uses the modern `.active()` queryset method which filters for:
      - committed (committer_id__isnull=False)
      - not entered in error (entered_in_error_id__isnull=True)
      - clinical_status = ACTIVE

    Args:
        patient_id: Patient UUID (external id / key)

    Returns:
        QuerySet of Condition objects missing an ICD-10 coding.
    """
    return list(
        Condition.objects.for_patient(patient_id)
        .active()
        .filter(surgical=False)
        .prefetch_related("codings")
        .exclude(codings__system=CodeSystems.ICD10)
    )
