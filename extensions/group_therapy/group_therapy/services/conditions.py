"""Per-patient active diagnosis lookups for group therapy assess commands."""

from canvas_sdk.v1.data.condition import Condition
from canvas_sdk.value_set.value_set import CodeConstants
from logger import log


def active_conditions(patient_id: str) -> list[dict]:
    """Return the patient's active, committed ICD-10 conditions as dicts.

    Each dict is ``{"id", "icd10_code", "display"}``. Codings are prefetched to
    avoid an N+1 across a roster of attendees. A lookup failure degrades to an
    empty list (logged) so one bad chart cannot break the roster UI.
    """
    results: list[dict] = []
    try:
        conditions = (
            Condition.objects.for_patient(patient_id)
            .active()
            .prefetch_related("codings")
        )
        for condition in conditions:
            for coding in condition.codings.all():
                if coding.system == CodeConstants.URL_ICD10:
                    results.append(
                        {
                            "id": str(condition.id),
                            "icd10_code": coding.code,
                            "display": coding.display or "",
                        }
                    )
                    break
    except (AttributeError, ValueError) as exc:
        log.warning(f"active_conditions failed for patient={patient_id}: {exc}")
    return results


def default_condition_id(conditions: list[dict]) -> str | None:
    """Auto-select the diagnosis only when the patient has exactly one active dx."""
    if len(conditions) == 1:
        return conditions[0]["id"]
    return None
