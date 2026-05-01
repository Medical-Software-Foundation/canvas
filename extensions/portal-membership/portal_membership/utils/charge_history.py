"""ORM-backed charge history.

Replaces the ``record["charges"]`` list that used to live on the cached
membership dict. Each entry is now a row in the ``ChargeRecord`` table.

``patient_id`` is normalised to its bare hex form here (matching
``membership_store``) so charges written under one UUID shape are still
visible when the portal session sends the other shape.
"""
from typing import Any

from portal_membership.models import ChargeRecord
from portal_membership.utils.membership_store import _normalise_patient_id

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
    ChargeRecord.objects.create(
        patient_id=_normalise_patient_id(patient_id),
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
    pid = _normalise_patient_id(patient_id)
    if not pid:
        return []
    try:
        qs = ChargeRecord.objects.filter(patient_id=pid).order_by("-charged_at")[:limit]
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
