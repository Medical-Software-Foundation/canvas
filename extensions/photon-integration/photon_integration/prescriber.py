"""Resolve the prescriber on a command to an identity we can match in Photon.

Photon attributes a prescription to the *authenticated* user (createPrescription
has no prescriberId). To stop a prescription being sent under the wrong Photon
account, we resolve the command's prescriber to an email and compare it, in the
browser, to the signed-in Photon user. Resolution is best-effort and never raises
— a missing email is treated downstream as "can't verify" (fail safe).
"""

from __future__ import annotations

from typing import Any

from canvas_sdk.v1.data.staff import Staff
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
    """Email for a Staff: prefer the linked CanvasUser, fall back to telecom."""
    try:
        user = staff.user
        if user and getattr(user, "email", None):
            return str(user.email).strip().lower() or None
    except Exception:  # noqa: BLE001
        pass
    try:
        from canvas_sdk.v1.data.common import ContactPointSystem

        contact = staff.telecom.filter(system=ContactPointSystem.EMAIL).first()
        if contact and contact.value:
            return str(contact.value).strip().lower() or None
    except Exception:  # noqa: BLE001
        pass
    return None


def resolve_prescriber(data: dict[str, Any]) -> dict[str, str | None]:
    """Return {'email', 'name'} for the command's prescriber (best effort)."""
    prescriber = data.get("prescriber")
    # Log the raw shape so we can refine resolution against real data.
    log.info("Photon prescriber field: %r", prescriber)
    ref, name = _prescriber_ref(prescriber)
    email: str | None = None
    if ref:
        try:
            staff = Staff.objects.filter(id=ref).first()
        except Exception as exc:  # noqa: BLE001 - never let resolution 500 the modal
            log.warning("Photon prescriber lookup failed for %r: %s", ref, exc)
            staff = None
        if staff:
            if not name:
                name = f"{staff.first_name or ''} {staff.last_name or ''}".strip() or None
            email = _staff_email(staff)
    return {"email": email, "name": name}
