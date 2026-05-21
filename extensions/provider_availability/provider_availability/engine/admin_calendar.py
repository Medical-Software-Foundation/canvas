"""Shared helpers for finding/creating Administrative calendars."""

from __future__ import annotations

import uuid

from canvas_sdk.effects import Effect
from canvas_sdk.effects.calendar import Calendar as CalendarEffect
from canvas_sdk.effects.calendar import CalendarType
from canvas_sdk.v1.data import PracticeLocation
from canvas_sdk.v1.data.calendar import Calendar as CalendarModel
from canvas_sdk.v1.data.staff import Staff
from logger import log


def get_admin_calendar_id(
    provider_id: str, location_id: str | None = None
) -> tuple[str, list[Effect]]:
    """Find or create the provider's Administrative calendar.

    When location_id is provided, returns a location-specific Admin calendar
    (mirroring how _get_calendar_id works for Clinic calendars).

    Returns (calendar_id, effects_needed_to_create).
    """
    try:
        staff = Staff.objects.get(id=provider_id)
        provider_name = staff.full_name
    except Staff.DoesNotExist:
        return "", []

    if not provider_name:
        return "", []

    location_name = ""
    if location_id:
        try:
            loc = PracticeLocation.objects.get(id=location_id)
            location_name = loc.full_name
        except PracticeLocation.DoesNotExist:
            pass

    loc_arg = location_name or None
    existing = CalendarModel.objects.for_calendar_name(
        provider_name=provider_name,
        calendar_type=CalendarType.Administrative,
        location=loc_arg,
    ).first()
    if existing:
        return str(existing.id), []

    new_id = str(uuid.uuid4())
    cal_effect = CalendarEffect(
        id=new_id,
        provider=provider_id,
        type=CalendarType.Administrative,
        location=location_id if location_id else None,
    ).create()
    log.info(
        "get_admin_calendar_id: creating Admin calendar id=%s for provider %s location=%s",
        new_id, provider_id, location_id,
    )
    return new_id, [cal_effect]


def get_admin_calendars(provider_id: str) -> list[CalendarModel]:
    """Find all Administrative calendars for a provider."""
    try:
        staff = Staff.objects.get(id=provider_id)
        provider_name = staff.full_name
    except Staff.DoesNotExist:
        return []

    if not provider_name:
        return []

    return list(
        CalendarModel.objects.filter(title__startswith=provider_name + ": Admin")
    )
