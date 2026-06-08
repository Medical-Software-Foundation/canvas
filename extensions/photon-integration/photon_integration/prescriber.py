"""Resolve the prescriber on a command to an identity we can match in Photon.

Photon attributes a prescription to the *authenticated* user (createPrescription
has no prescriberId). To stop a prescription being sent under the wrong Photon
account, we resolve the command's prescriber to an email and compare it, in the
browser, to the signed-in Photon user.
"""

from __future__ import annotations

from typing import Any

from canvas_sdk.v1.data.common import ContactPointSystem
from canvas_sdk.v1.data.staff import Staff

_PRESCRIBER_ID_KEYS = ("value", "id", "key", "staff", "staff_id")


def _prescriber_ref(data: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return (id/ref, display name) from the command's prescriber field."""
    prescriber = data.get("prescriber")
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


def resolve_prescriber(data: dict[str, Any]) -> dict[str, str | None]:
    """Return {'email', 'name'} for the command's prescriber (best effort)."""
    ref, name = _prescriber_ref(data)
    email: str | None = None
    if ref:
        staff = (
            Staff.objects.filter(user__id=ref).first()
            or Staff.objects.filter(id=ref).first()
        )
        if staff:
            if not name:
                name = f"{staff.first_name or ''} {staff.last_name or ''}".strip() or None
            contact = staff.telecom.filter(system=ContactPointSystem.EMAIL).first()
            if contact and contact.value:
                email = str(contact.value).strip().lower()
    return {"email": email, "name": name}
