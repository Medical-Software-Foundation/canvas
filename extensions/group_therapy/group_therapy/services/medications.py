"""Read-only active medication list for the screening template (pulled from chart)."""

from canvas_sdk.v1.data.medication import Medication
from logger import log


def active_medications(patient_id: str) -> list[str]:
    """Return the patient's active medication display names (read-only)."""
    names: list[str] = []
    try:
        meds = (
            Medication.objects.for_patient(patient_id).active().prefetch_related("codings")
        )
        for med in meds:
            for coding in med.codings.all():
                if coding.display:
                    names.append(coding.display)
                    break
    except (AttributeError, ValueError) as exc:
        log.warning(f"active_medications failed for patient={patient_id}: {exc}")
    return names
