"""ORM-backed membership state store.

Replaces the plugin-cache-backed implementation. All state lives on the
``Membership`` custom model; the 14-day cache TTL is no longer a factor.

The public API (``get_membership`` / ``set_membership``) still returns/accepts
dicts so callers don't need to learn the ORM — mutation-and-write remains the
pattern. A field missing from the dict on write is interpreted as "reset to
default", matching the pre-ORM behaviour where ``record.pop(field, None)``
would drop it from the cached record entirely.

All public functions normalise *patient_id* to its bare 32-char hex form
(no hyphens). Canvas sometimes hands the plugin a UUID with hyphens (widget
event context) and sometimes without (SimpleAPI session header) — we collapse
both shapes to one canonical form so the row written at signup matches the
row looked up on subsequent reads.
"""
from datetime import date
from typing import Any

from django.db import IntegrityError

from logger import log

from portal_membership.models import Membership

# Transient status used as a DB-backed mutex during /signup and /restart —
# see ``try_claim_signup`` / ``release_claim``.
PENDING_SIGNUP_STATUS = "pending_signup"

# Scalar fields mirrored between dict and model.
_SCALAR_FIELDS = [
    "plan",
    "plan_name",
    "status",
    "stripe_customer_id",
    "payment_method_id",
    "amount_cents",
    "currency",
    "cadence",
    "billing_day",
    "consecutive_failures",
    "discount_code",
    "discount_type",
    "discount_value",
    "discount_cycles_remaining",
]

# Nullable date fields stored as ISO-8601 strings in the dict API.
_DATE_FIELDS = ["next_billing_date", "retry_date"]

# Scalar defaults used when a key is absent from the dict on write.
_SCALAR_DEFAULTS: dict[str, Any] = {
    "payment_method_id": "",
    "currency": "usd",
    "cadence": "monthly",
    "consecutive_failures": 0,
    "discount_code": "",
    "discount_type": "",
    "discount_value": 0,
    "discount_cycles_remaining": 0,
}


def _normalise_patient_id(patient_id: str | None) -> str:
    """Return *patient_id* without hyphens — the canonical storage form."""
    if not patient_id:
        return ""
    return patient_id.replace("-", "")


def get_membership(patient_id: str) -> dict[str, Any] | None:
    """Return the membership record for *patient_id* as a dict, or ``None``.

    Returns ``None`` for any lookup failure — missing row, malformed id, DB
    error, namespace not yet provisioned. Callers treat "no record" as "not
    enrolled", which is the correct user-facing fall-back.
    """
    pid = _normalise_patient_id(patient_id)
    if not pid:
        return None
    try:
        instance = Membership.objects.get(patient_id=pid)
    except Membership.DoesNotExist:
        return None
    except Exception as exc:  # noqa: BLE001 — log and fall back for widget safety
        log.warning(
            f"portal_membership: get_membership failed for patient_id={patient_id!r}: "
            f"{type(exc).__name__}: {exc}"
        )
        return None
    return _to_dict(instance)


def set_membership(patient_id: str, data: dict[str, Any]) -> None:
    """Upsert the membership record for *patient_id* from a dict."""
    Membership.objects.update_or_create(
        patient_id=_normalise_patient_id(patient_id),
        defaults=_from_dict(data),
    )


def delete_membership(patient_id: str) -> None:
    """Remove the membership record for *patient_id* (idempotent)."""
    pid = _normalise_patient_id(patient_id)
    if not pid:
        return
    Membership.objects.filter(patient_id=pid).delete()


def try_claim_signup(patient_id: str) -> tuple[str, str | None]:
    """Atomically claim a signup slot for *patient_id*.

    Acts as the race guard for ``/signup`` and ``/restart``: only one
    concurrent request can advance past the claim to the Stripe call,
    preventing duplicate Stripe customers and double charges when the same
    patient submits the form twice in quick succession.

    Returns ``(result, prior_status)``:
      * ``("claimed", None)`` — no prior row; a fresh pending row was created.
      * ``("claimed", "<status>")`` — an existing row was transitioned to
        pending_signup; ``<status>`` is what to revert to on Stripe failure.
      * ``("already_active", None)`` — caller already has an active membership.
      * ``("in_progress", None)`` — another signup is currently in flight.

    The returned ``prior_status`` must be passed back to ``release_claim`` so
    a newly-created pending row is deleted on rollback while a transitioned
    row is reverted to its original state.
    """
    pid = _normalise_patient_id(patient_id)
    if not pid:
        return ("in_progress", None)

    try:
        existing = Membership.objects.get(patient_id=pid)
    except Membership.DoesNotExist:
        existing = None
    except Exception as exc:  # noqa: BLE001 — fail closed on DB errors
        log.warning(
            f"portal_membership: try_claim_signup lookup failed for "
            f"patient_id={patient_id!r}: {type(exc).__name__}: {exc}"
        )
        return ("in_progress", None)

    if existing is not None:
        if existing.status == "active":
            return ("already_active", None)
        if existing.status == PENDING_SIGNUP_STATUS:
            return ("in_progress", None)
        # Conditional UPDATE keyed on the prior status: only the first caller
        # to observe that status wins — PostgreSQL serializes the match.
        prior_status = existing.status
        updated = Membership.objects.filter(
            patient_id=pid,
            status=prior_status,
        ).update(status=PENDING_SIGNUP_STATUS)
        if updated == 0:
            return ("in_progress", None)
        return ("claimed", prior_status)

    # No row yet — insert. The UniqueConstraint on patient_id makes the second
    # concurrent insert raise IntegrityError.
    today = date.today()
    try:
        Membership.objects.create(
            patient_id=pid,
            plan="",
            plan_name="",
            status=PENDING_SIGNUP_STATUS,
            stripe_customer_id="",
            amount_cents=0,
            billing_day=today.day,
            next_billing_date=today,
        )
    except IntegrityError:
        return ("in_progress", None)
    return ("claimed", None)


def release_claim(patient_id: str, prior_status: str | None) -> None:
    """Revert a pending_signup claim after a failed Stripe call.

    When ``prior_status`` is ``None`` the pending row was newly created by
    ``try_claim_signup`` and is deleted. Otherwise the row is reverted to
    ``prior_status``. Both operations are scoped to rows still in the
    pending_signup state, so a concurrent finalize won't be stomped on.
    """
    pid = _normalise_patient_id(patient_id)
    if not pid:
        return
    qs = Membership.objects.filter(
        patient_id=pid,
        status=PENDING_SIGNUP_STATUS,
    )
    if prior_status is None:
        qs.delete()
    else:
        qs.update(status=prior_status)


# ---------------------------------------------------------------------------
# Dict ↔ model conversion
# ---------------------------------------------------------------------------

def _to_dict(instance: Membership) -> dict[str, Any]:
    """Return the membership record as a dict with ISO-date strings."""
    record: dict[str, Any] = {field: getattr(instance, field) for field in _SCALAR_FIELDS}
    for field in _DATE_FIELDS:
        value = getattr(instance, field)
        record[field] = value.isoformat() if value else None
    # Caller convenience: keep the None-out-of-the-dict shape for retry_date.
    if record["retry_date"] is None:
        record.pop("retry_date")
    # Drop empty discount fields so callers see the same shape as pre-ORM —
    # absence of discount_code means "no discount".
    if not record.get("discount_code"):
        for k in ("discount_code", "discount_type", "discount_value", "discount_cycles_remaining"):
            record.pop(k, None)
    return record


def _from_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Convert a record dict into ``update_or_create(defaults=...)`` kwargs.

    Any field missing from *data* is reset to its default (for scalars) or
    ``None`` (for nullable dates). This matches the pre-ORM behaviour where
    ``record.pop(field)`` removed the key and the cache write persisted the
    absence.
    """
    fields: dict[str, Any] = {}
    for name in _SCALAR_FIELDS:
        fields[name] = data.get(name, _SCALAR_DEFAULTS.get(name, ""))
    for name in _DATE_FIELDS:
        raw = data.get(name)
        if not raw:
            fields[name] = None
        elif isinstance(raw, date):
            fields[name] = raw
        else:
            fields[name] = date.fromisoformat(str(raw))
    return fields
