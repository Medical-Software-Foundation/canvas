"""Resolve a Salesforce record id to its linked Canvas patient.

The create flow writes a :class:`PatientExternalIdentifier` row with
``system="salesforce"`` and ``value=<sf_id>`` for every patient it lands. The
modify audit row reuses that identifier to find the Canvas patient that the
update should target. A modify with no matching identifier is unlinkable and
surfaces to the operator as a warning in the audit table.
"""

from datetime import date
from typing import Any

from canvas_sdk.v1.data.patient import Patient

SALESFORCE_IDENTIFIER_SYSTEM = "salesforce"

# Cap on duplicate matches returned so a wide last name plus birth date collision
# can never blow the JSON payload the audit modal renders.
DUPLICATE_MATCH_LIMIT = 10


def find_linked_patient_id(sf_record_id: str) -> str | None:
    """Return the Canvas Patient id tied to a Salesforce record, or None.

    Returns the string ``Patient.id`` rather than a Patient instance so the
    caller can hand it straight to :func:`build_update_patient_effect` without
    paying for the full row load.
    """
    if not sf_record_id:
        return None
    pid = (
        Patient.objects.filter(
            external_identifiers__system=SALESFORCE_IDENTIFIER_SYSTEM,
            external_identifiers__value=sf_record_id,
        )
        .values_list("id", flat=True)
        .first()
    )
    return str(pid) if pid is not None else None


def find_duplicate_patients(
    *, last_name: str, birth_date: date, limit: int = DUPLICATE_MATCH_LIMIT
) -> list[dict[str, Any]]:
    """Find Canvas patients sharing a last name and birth date.

    The match shape mirrors the home app ``DuplicatePatientWarning`` lookup,
    case insensitive last name plus an exact birth date. Both the duplicate
    check route that drives the audit modal warning and the webhook auto apply
    gate read through here so the surfaced duplicates and the gated duplicates
    can never drift. Results are capped at ``limit``. Returns the raw value rows,
    the caller formats them for its own payload.
    """
    if not last_name:
        return []
    rows = (
        Patient.objects.filter(last_name__iexact=last_name, birth_date=birth_date)
        .values("id", "first_name", "last_name", "birth_date")[:limit]
    )
    return [dict(row) for row in rows]


__all__ = (
    "DUPLICATE_MATCH_LIMIT",
    "SALESFORCE_IDENTIFIER_SYSTEM",
    "find_duplicate_patients",
    "find_linked_patient_id",
)
