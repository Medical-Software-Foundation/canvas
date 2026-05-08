"""ORM-backed charge history.

Replaces the ``record["charges"]`` list that used to live on the cached
membership dict. Each entry is now a row in the ``ChargeRecord`` table.

``patient`` is a ``ForeignKey`` to ``PatientProxy``; the public API still
takes UUID strings and resolves them to a Patient ``dbid`` for FK writes.
"""
from typing import Any

from portal_membership.models import ChargeRecord
from portal_membership.utils.membership_store import _resolve_patient_dbid

DEFAULT_LIMIT = 50


def append_charge(
    patient_id: str,
    *,
    amount_cents: int,
    status: str,
    description: str,
    discount_code: str | None = None,
) -> None:
    """Persist a charge attempt for *patient_id*."""
    dbid = _resolve_patient_dbid(patient_id)
    if dbid is None:
        return
    ChargeRecord.objects.create(
        patient_id=dbid,
        amount_cents=int(amount_cents),
        status=status,
        description=description,
        discount_code=discount_code or "",
    )


def get_charges(patient_id: str, limit: int = DEFAULT_LIMIT) -> list[dict[str, Any]]:
    """Return the patient's recent charges, newest first.

    Returns an empty list for any lookup failure — malformed id, DB error,
    namespace not yet provisioned.
    """
    if not patient_id:
        return []
    try:
        qs = (
            ChargeRecord.objects.filter(patient__id=patient_id)
            .order_by("-charged_at")[:limit]
        )
        return [_to_dict(c) for c in qs]
    except Exception:  # noqa: BLE001 — history panel should degrade to empty, never crash
        return []


def _to_dict(record: ChargeRecord) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "date": record.charged_at.date().isoformat(),
        "amount_cents": record.amount_cents,
        "status": record.status,
        "description": record.description,
    }
    if record.discount_code:
        entry["discount_code"] = record.discount_code
    return entry
