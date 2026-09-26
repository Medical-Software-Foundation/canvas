"""Custom-data-backed dismissal store for medication history items.

Dismissals are stored in the vicert__rx_history custom data namespace so
they persist across plugin reloads rather than living in the plugin cache.
"""
from __future__ import annotations

from rx_history.models.dismissed_medication import DismissedMedication
from rx_history.models.proxy import PatientProxy, StaffProxy

from logger import log


def dismiss(
    patient_id: str,
    staff_id: str,
    drug_description: str,
    ndc_code: str,
    last_fill_date: str,
) -> None:
    """Record a dismissal. Idempotent via UniqueConstraint on the row."""
    patient = PatientProxy.objects.get(id=patient_id)
    staff = StaffProxy.objects.get(id=staff_id)
    DismissedMedication.objects.get_or_create(
        patient=patient,
        drug_description=drug_description,
        ndc_code=ndc_code or "",
        last_fill_date=last_fill_date or "",
        defaults={"dismissed_by": staff},
    )
    log.info(
        "Dismissed medication for patient %s: %s" % (patient_id, drug_description)
    )


def is_dismissed(
    patient_id: str,
    drug_description: str,
    ndc_code: str,
    last_fill_date: str,
) -> bool:
    """Match on all three fields so a new fill of the same drug (different
    last_fill_date) shows up as new. Tamiflu-this-year vs Tamiflu-last-year."""
    return bool(
        DismissedMedication.objects.filter(
            patient__id=patient_id,
            drug_description=drug_description,
            ndc_code=ndc_code or "",
            last_fill_date=last_fill_date or "",
        ).exists()
    )


def get_dismissed_keys(patient_id: str) -> set[tuple[str, str, str]]:
    """Return the full dismissal key set for a patient in a single query.

    Callers that need to check many items against the dismissal list should
    use this helper and a local set lookup, rather than calling is_dismissed
    in a loop. Keys are normalized the same way as writes: empty string for
    missing ndc_code and last_fill_date.
    """
    return {
        (r.drug_description, r.ndc_code, r.last_fill_date)
        for r in DismissedMedication.objects.filter(patient__id=patient_id)
    }


def get_dismissals(patient_id: str) -> list[dict]:
    """Return all dismissal entries for a patient."""
    rows = DismissedMedication.objects.filter(patient__id=patient_id).order_by(
        "-dismissed_at"
    )
    return [
        {
            "drug_description": r.drug_description,
            "ndc_code": r.ndc_code,
            "last_fill_date": r.last_fill_date,
            "dismissed_at": r.dismissed_at.isoformat() if r.dismissed_at else "",
        }
        for r in rows
    ]


def undo_dismissal(
    patient_id: str,
    drug_description: str,
    ndc_code: str,
    last_fill_date: str,
) -> bool:
    """Remove a dismissal entry. Returns True if a row was deleted."""
    deleted_count, _ = DismissedMedication.objects.filter(
        patient__id=patient_id,
        drug_description=drug_description,
        ndc_code=ndc_code or "",
        last_fill_date=last_fill_date or "",
    ).delete()
    if deleted_count > 0:
        log.info(
            "Undid dismissal for patient %s: %s" % (patient_id, drug_description)
        )
        return True
    return False
