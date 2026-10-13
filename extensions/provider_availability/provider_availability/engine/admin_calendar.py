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


def name_is_shared(provider_id: str) -> bool:
    """Whether another staff record has this provider's exact first and last name.

    One person can have several profiles (one per licensing state, say), and
    calendars are linked to a provider only by name, so for shared names a
    name-only calendar cannot be told apart and is not reused.
    """
    row = Staff.objects.filter(id=provider_id).values_list("first_name", "last_name").first()
    if not row:
        return False
    return bool(Staff.objects.filter(first_name=row[0], last_name=row[1]).exclude(id=provider_id).exists())


def find_own_calendar(
    provider_id: str, provider_name: str, calendar_type: str, location_name: str | None, fixed_id: str
) -> CalendarModel | None:
    """The calendar of this type (and location) that belongs to this provider, if any.

    In order: the fixed id the plugin gives calendars it creates; a calendar
    with the right title tagged with this provider's staff key; and, only when
    no other staff record shares the name, an untagged calendar with the right
    title (made before calendars were tagged).
    """
    by_id = CalendarModel.objects.filter(id=fixed_id).first()
    if by_id:
        return by_id
    title = f"{provider_name}: {calendar_type}" + (f": {location_name}" if location_name else "")
    candidates = list(CalendarModel.objects.filter(title=title))
    mine = next((c for c in candidates if c.description == str(provider_id)), None)
    if mine or not candidates:
        return mine
    if name_is_shared(provider_id):
        return None
    return next((c for c in candidates if not c.description), candidates[0])


def own_calendars_q(provider_id: str, provider_name: str, calendar_type: str | None = None) -> Q:
    """Calendars to clear or read for this provider: tagged with its staff key, or
    untagged with its name. Calendars tagged for another profile with the same
    name are left out, so one profile never clears another's events.
    """
    prefix = f"{provider_name}: {calendar_type}" if calendar_type else f"{provider_name}:"
    untagged = Q(description="") | Q(description__isnull=True)
    return Q(title__startswith=prefix) & (Q(description=str(provider_id)) | untagged)


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
    existing = find_own_calendar(
        provider_id, provider_name, CalendarType.Administrative, location_name or None, new_id
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
        CalendarModel.objects.filter(own_calendars_q(provider_id, provider_name, CalendarType.Administrative))
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
