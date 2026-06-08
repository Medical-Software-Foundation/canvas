"""Resolve the prescriber on a command to an identity we can match in Photon.

Photon attributes a prescription to the *authenticated* user (createPrescription
has no prescriberId). To stop a prescription being sent under the wrong Photon
account, we resolve the command's prescriber to an email and compare it, in the
browser, to the signed-in Photon user. Resolution is best-effort: *expected*
lookup failures (a missing CanvasUser relation, a DB error) degrade to "no email"
— treated downstream as "can't verify" (fail safe) — while unexpected errors are
allowed to propagate so they reach Sentry rather than being silently masked.
"""

from __future__ import annotations

from typing import Any

from canvas_sdk.v1.data.common import ContactPointSystem
from canvas_sdk.v1.data.staff import Staff
from django.core.exceptions import ObjectDoesNotExist
from django.db import DatabaseError
from logger import log

_PRESCRIBER_ID_KEYS = ("value", "id", "key", "staff", "staff_id")


def _prescriber_ref(prescriber: Any) -> tuple[str | None, str | None]:
    """Return (id/ref, display name) from the command's prescriber field."""
    if isinstance(prescriber, str):
        return (prescriber.strip() or None, None)
    if isinstance(prescriber, dict):
        ref = None
        for key in _PRESCRIBER_ID_KEYS:
            value = prescriber.get(key)
            if value:
                ref = str(value)
                break
        return (ref, prescriber.get("text") or None)
    return (None, None)


def _staff_email(staff: Staff) -> str | None:
    """Email for a Staff: prefer the linked CanvasUser, fall back to telecom.

    Catches only the expected failures — a missing ``user`` relation
    (``ObjectDoesNotExist``) or a DB error — and degrades to ``None``; anything
    else propagates.
    """
    try:
        user = staff.user
        if user and getattr(user, "email", None):
            return str(user.email).strip().lower() or None
        contact = staff.telecom.filter(system=ContactPointSystem.EMAIL).first()
        if contact and contact.value:
            return str(contact.value).strip().lower() or None
    except (ObjectDoesNotExist, DatabaseError) as exc:
        log.warning("Photon staff email lookup failed: %s", exc)
    return None


def _staff_for_ref(ref: str) -> Staff | None:
    """Look up a Staff by the command's prescriber ref.

    The prescriber ``value`` is the Staff integer pk (``dbid``); fall back to the
    public ``id`` (UUID) for other shapes. A DB error degrades to ``None``;
    unexpected errors propagate.
    """
    # select_related("user") folds the CanvasUser join in so reading
    # staff.user.email in _staff_email doesn't trigger a second query.
    staff = Staff.objects.select_related("user")
    try:
        if ref.isdigit():
            return staff.filter(dbid=int(ref)).first()
        return staff.filter(id=ref).first()
    except DatabaseError as exc:
        log.warning("Photon prescriber lookup failed for %r: %s", ref, exc)
        return None


def staff_identity(ref: Any, fallback_name: str | None = None) -> dict[str, str | None]:
    """Return {'email', 'name'} for a Staff ref (dbid or public id). Never raises."""
    name = fallback_name
    email: str | None = None
    if ref not in (None, ""):
        staff = _staff_for_ref(str(ref))
        if staff:
            if not name:
                name = f"{staff.first_name or ''} {staff.last_name or ''}".strip() or None
            email = _staff_email(staff)
    return {"email": email, "name": name}


def resolve_prescriber(data: dict[str, Any]) -> dict[str, str | None]:
    """Return {'email', 'name'} for the command's prescriber (best effort)."""
    ref, name = _prescriber_ref(data.get("prescriber"))
    return staff_identity(ref, fallback_name=name)
