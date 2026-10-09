"""Shared helpers for finding/creating Administrative calendars."""

from __future__ import annotations

import uuid

from django.db.models import Q

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


def resolve_provider_name(provider_id: str) -> str:
    """Return a provider's full name, or '' if the staff record is missing.

    Callers that loop over locations should resolve this ONCE and pass it into
    get_admin_calendar_id / get_admin_calendars to avoid refetching the same
    Staff row per iteration.
    """
    row = Staff.objects.filter(id=provider_id).values_list("first_name", "last_name").first()
    if not row:
        return ""
    # Same text as Staff.full_name, without loading the whole staff row.
    name = f"{row[0]} {row[1]}"
    return name if name.strip() else ""


def get_admin_calendar_id(
    provider_id: str, location_id: str | None = None, provider_name: str | None = None
) -> tuple[str, list[Effect]]:
    """Find or create the provider's Administrative calendar.

    When location_id is provided, returns a location-specific Admin calendar
    (mirroring how _get_calendar_id works for Clinic calendars).

    Pass provider_name to skip the Staff lookup (resolve once before a loop).

    Returns (calendar_id, effects_needed_to_create).
    """
    if provider_name is None:
        provider_name = resolve_provider_name(provider_id)

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


def get_admin_calendars(
    provider_id: str, provider_name: str | None = None
) -> list[CalendarModel]:
    """Find all Administrative calendars for a provider.

    Pass provider_name to skip the Staff lookup (resolve once before a loop).
    """
    if provider_name is None:
        provider_name = resolve_provider_name(provider_id)

    if not provider_name:
        return []

    return list(
        CalendarModel.objects.filter(title__startswith=provider_name + ": Admin")
    )


def missing_clinic_calendar_effects(staff_list: list[Staff]) -> list[Effect]:
    """Create effects for staff with no provider-level Clinic calendar, found in one query.

    A calendar counts as theirs if it has the deterministic id, the standard
    "Name: Clinic" title, or their staff key as description on a Clinic title
    (covers a renamed provider). New calendars get the deterministic id, so two
    runners creating one at once write the same calendar.
    """
    wanted = {
        str(s.id): (deterministic_calendar_id(str(s.id), CalendarType.Clinic, None), f"{s.full_name}: {CalendarType.Clinic}")
        for s in staff_list
    }
    if not wanted:
        return []
    rows = CalendarModel.objects.filter(
        Q(id__in=[cid for cid, _ in wanted.values()])
        | Q(title__in=[title for _, title in wanted.values()])
        | Q(description__in=list(wanted), title__endswith=f": {CalendarType.Clinic}")
    ).values_list("id", "title", "description")
    have_ids = {str(r[0]) for r in rows}
    have_titles = {r[1] for r in rows}
    have_keys = {r[2] for r in rows if r[1].endswith(f": {CalendarType.Clinic}")}
    return [
        CalendarEffect(id=cid, provider=key, type=CalendarType.Clinic, description=key).create()
        for key, (cid, title) in wanted.items()
        if cid not in have_ids and title not in have_titles and key not in have_keys
    ]
