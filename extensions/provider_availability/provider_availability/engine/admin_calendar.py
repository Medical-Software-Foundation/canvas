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

# Fixed namespace for deriving deterministic calendar ids. Minting the calendar
# id from (provider, type, location) means two concurrent creates (e.g. the
# web + worker runners both handling an install) compute the SAME id, so the
# loser collides on the uuid and fails benignly instead of forking a duplicate
# calendar with a "-2" slug. Random ids let both creates succeed → duplicates.
_CALENDAR_NS = uuid.UUID("7f1d5a1e-0b3a-4e2c-9a6f-9b1c2d3e4f50")


def deterministic_calendar_id(
    provider_id: str, calendar_type: str, location_id: str | None = None
) -> str:
    """Stable calendar id for a provider+type+location, race-safe across runners."""
    key = f"provider_availability:{provider_id}:{calendar_type}:{location_id or ''}"
    return str(uuid.uuid5(_CALENDAR_NS, key))


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

    new_id = deterministic_calendar_id(provider_id, CalendarType.Administrative, location_id)
    loc_arg = location_name or None
    # Prefer the deterministic anchor id (so a calendar we already created is
    # reused without re-emitting a create); fall back to title for legacy
    # calendars created before deterministic ids existed.
    existing = (
        CalendarModel.objects.filter(id=new_id).first()
        or CalendarModel.objects.for_calendar_name(
            provider_name=provider_name,
            calendar_type=CalendarType.Administrative,
            location=loc_arg,
        ).first()
    )
    if existing:
        return str(existing.id), []

    cal_effect = CalendarEffect(
        id=new_id,
        provider=provider_id,
        type=CalendarType.Administrative,
        location=location_id if location_id else None,
        # Store the staff UUID in description so the calendar can be resolved
        # back to its provider even if the provider is later renamed (title is
        # name-based). Mirrors the scheduling_with_rooms pattern.
        description=str(provider_id),
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
