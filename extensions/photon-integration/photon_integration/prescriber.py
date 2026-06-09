"""Resolve the prescriber on a command to an identity we can match in Photon.

Photon attributes a prescription to the *authenticated* user (createPrescription
has no prescriberId). To stop a prescription being sent under the wrong Photon
account, we resolve the command's prescriber to an email and compare it, in the
browser, to the signed-in Photon user. Expected "no data" cases (a Staff with no
linked user, no telecom, or no match for the ref) resolve to ``None`` natively —
no broad ``except`` — so any real error (DB outage, schema bug) surfaces to Sentry
instead of being silently masked. (The plugin sandbox also forbids importing the
``django`` exception classes, so catching them by type isn't an option anyway.)
"""

from __future__ import annotations

from typing import Any

from canvas_sdk.v1.data.common import ContactPointSystem
from canvas_sdk.v1.data.staff import Staff

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

    ``Staff.user`` is a nullable OneToOne (``None`` when unset) and ``telecom``
    yields ``None`` when empty, so the expected "no email" cases need no exception
    handling; a real error surfaces.
    """
    user = staff.user
    if user and getattr(user, "email", None):
        return str(user.email).strip().lower() or None
    contact = staff.telecom.filter(system=ContactPointSystem.EMAIL).first()
    if contact and contact.value:
        return str(contact.value).strip().lower() or None
    return None


def _staff_for_ref(ref: str) -> Staff | None:
    """Look up a Staff by the command's prescriber ref.

    The prescriber ``value`` is the Staff integer pk (``dbid``); fall back to the
    public ``id`` (UUID) for other shapes. A missing match resolves to ``None``
    via ``.first()``; a real DB error surfaces.
    """
    # select_related("user") folds the CanvasUser join in so reading
    # staff.user in _staff_email doesn't trigger a second query.
    staff = Staff.objects.select_related("user")
    if ref.isdigit():
        return staff.filter(dbid=int(ref)).first()
    return staff.filter(id=ref).first()


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
