"""Find or create a provider's Administrative calendar.

Mirrors the provider-availability plugin's ``get_admin_calendar_id``: a
find-or-create helper returning ``(calendar_id, effects_needed_to_create)``.
"""

from __future__ import annotations

import uuid

from canvas_sdk.effects import Effect
from canvas_sdk.effects.calendar import Calendar as CalendarEffect
from canvas_sdk.effects.calendar import CalendarType
from canvas_sdk.v1.data.calendar import Calendar as CalendarModel
from canvas_sdk.v1.data.staff import Staff
from logger import log


def _provider_name(provider_id: str) -> str | None:
    """Resolve a staff member's display name, or ``None`` if it can't be found."""
    try:
        staff = Staff.objects.get(id=provider_id)
    except Staff.DoesNotExist:
        return None
    return staff.full_name or None


def _existing_admin_calendar_id(provider_name: str) -> str:
    existing = CalendarModel.objects.for_calendar_name(
        provider_name=provider_name,
        calendar_type=CalendarType.Administrative,
        location=None,
    ).first()
    # `id` is a UUID. The Event effect json-serializes calendar_id as-is, so a
    # UUID object raises "Object of type UUID is not JSON serializable".
    return str(existing.id) if existing else ""


def find_admin_calendar_id(provider_id: str) -> str:
    """Return the provider's existing Admin calendar id, or ``""`` if none.

    Look-up only. Unlike :func:`get_admin_calendar_id` this never provisions a
    calendar, so callers that only read or clean up existing blocks (disconnect,
    status) don't create an empty calendar as a side effect.
    """
    provider_name = _provider_name(provider_id)
    if not provider_name:
        return ""
    return _existing_admin_calendar_id(provider_name)


def get_admin_calendar_id(provider_id: str) -> tuple[str, list[Effect]]:
    """Find or create the provider's Administrative calendar.

    Returns ``(calendar_id, effects_needed_to_create)``. When the provider
    already has an Admin calendar the effects list is empty. When the staff or
    their name cannot be resolved, returns ``("", [])``.
    """
    provider_name = _provider_name(provider_id)
    if not provider_name:
        return "", []

    existing_id = _existing_admin_calendar_id(provider_name)
    if existing_id:
        return existing_id, []

    new_id = str(uuid.uuid4())
    cal_effect = CalendarEffect(
        id=new_id,
        provider=provider_id,
        type=CalendarType.Administrative,
        location=None,
    ).create()
    log.info(
        "get_admin_calendar_id: creating Admin calendar id=%s for provider %s",
        new_id,
        provider_id,
    )
    return new_id, [cal_effect]
