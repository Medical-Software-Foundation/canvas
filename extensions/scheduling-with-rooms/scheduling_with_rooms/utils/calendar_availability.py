"""Calendar-based availability: parse titles, expand RRULE, get availability windows."""

from __future__ import annotations

import datetime
from typing import Any
from zoneinfo import ZoneInfo

from canvas_sdk.v1.data.calendar import Calendar, Event
from canvas_sdk.v1.data.practicelocation import PracticeLocation
from canvas_sdk.v1.data.staff import Staff
from logger import log


# Map RRULE BYDAY abbreviations to Python weekday numbers (Monday=0).
_DAY_MAP = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def parse_calendar_title(title: str) -> tuple[str, str, str | None]:
    """Parse a calendar title into (staff_name, calendar_type, location_name | None).

    Format: "{Staff Name}: {Type}" or "{Staff Name}: {Type}: {Location Name}"
    Examples:
        "Christopher Taylor: Clinic: Florida location"
            -> ("Christopher Taylor", "Clinic", "Florida location")
        "Richard Wilson: Clinic"
            -> ("Richard Wilson", "Clinic", None)
    """
    parts = [p.strip() for p in title.split(":")]
    if len(parts) >= 3:
        # Rejoin parts 2+ in case location name itself contains ":"
        return parts[0], parts[1], ":".join(parts[2:]).strip()
    if len(parts) == 2:
        return parts[0], parts[1], None
    return title.strip(), "", None


def _parse_rrule(rrule_str: str) -> dict[str, str]:
    """Parse an RRULE string into a dict of key=value components."""
    rule = rrule_str.replace("RRULE:", "")
    result: dict[str, str] = {}
    for part in rule.split(";"):
        if "=" in part:
            key, value = part.split("=", 1)
            result[key] = value
    return result


def event_occurs_on_date(event: Event, target_date: datetime.date) -> bool:
    """Check if a (possibly recurring) calendar event occurs on target_date."""
    if not event.starts_at:
        return False

    if not event.recurrence:
        return bool(event.starts_at.date() == target_date)

    # Event must have started on or before the target date.
    if target_date < event.starts_at.date():
        return False

    # Recurrence end date. Canvas stores this in the separate
    # ``recurrence_ends_at`` column, NOT as an UNTIL= inside the RRULE string
    # (the rule is often just "FREQ=DAILY"). Without honoring this column a
    # time-bounded block — e.g. an "Out of Office" that ends June 6 — recurs
    # forever and silently zeroes out availability for every later date.
    if event.recurrence_ends_at and target_date > event.recurrence_ends_at.date():
        return False

    rule = _parse_rrule(event.recurrence)
    freq = rule.get("FREQ", "")

    # UNTIL check (when the end date is embedded in the RRULE string instead).
    until_str = rule.get("UNTIL")
    if until_str:
        try:
            until_dt = datetime.datetime.strptime(until_str[:15], "%Y%m%dT%H%M%S")
            if target_date > until_dt.date():
                return False
        except ValueError:
            pass

    interval = int(rule.get("INTERVAL", "1"))

    if freq == "DAILY":
        if interval == 1:
            return True
        days_diff = (target_date - event.starts_at.date()).days
        return bool(days_diff % interval == 0)

    if freq == "WEEKLY":
        byday = rule.get("BYDAY", "")
        allowed_days = {
            _DAY_MAP[d.strip()]
            for d in byday.split(",")
            if d.strip() in _DAY_MAP
        }
        # A FREQ=WEEKLY rule with no (parseable) BYDAY recurs on the same
        # weekday as the event's start — RFC 5545 DTSTART semantics. The SDK
        # only writes BYDAY when recurrence_days is set, so a weekly event
        # created from just a start datetime has none. Without this fallback
        # the rule matches every day of the week, so a Tue/Thu "Out of Office"
        # block silently zeroed out Mon/Wed/Fri availability too.
        if not allowed_days:
            allowed_days = {event.starts_at.weekday()}
        if target_date.weekday() not in allowed_days:
            return False

        if interval > 1:
            weeks_diff = (target_date - event.starts_at.date()).days // 7
            if weeks_diff % interval != 0:
                return False

        return True

    # Unsupported FREQ — conservatively say no.
    return False


def _event_window_on_date(
    event: Event,
    target_date: datetime.date,
    calendar_tz: ZoneInfo,
) -> tuple[datetime.datetime, datetime.datetime] | None:
    """Return the (naive-local) start/end window for an event on target_date.

    Converts the event's UTC start/end to the calendar's timezone, extracts the
    time-of-day, and applies it to target_date as a naive local datetime.

    When the event's local end time falls on a later day than its local start
    (i.e. the event spans past midnight), the window is capped at 23:59:59 on
    the target date so it still produces a valid availability window.
    """
    if not event.starts_at or not event.ends_at:
        return None

    local_start = event.starts_at.astimezone(calendar_tz)
    local_end = event.ends_at.astimezone(calendar_tz)

    window_start = datetime.datetime(
        target_date.year, target_date.month, target_date.day,
        local_start.hour, local_start.minute, local_start.second,
    )

    # If the event spans past midnight in local time, cap at end of day.
    if local_end.date() > local_start.date():
        window_end = datetime.datetime(
            target_date.year, target_date.month, target_date.day,
            23, 59, 59,
        )
    else:
        window_end = datetime.datetime(
            target_date.year, target_date.month, target_date.day,
            local_end.hour, local_end.minute, local_end.second,
        )

    if window_end <= window_start:
        return None
    return (window_start, window_end)


def _staff_calendars(staff, type_keyword: str = "Clinic"):
    """Return calendars that belong to ``staff`` of the given type.

    Both of these lookups contribute, deduped by id:
      1. ``description`` contains the staff UUID (dashed or hex form) AND the
         title contains the type keyword (Clinic / admin). Resilient to staff
         renames because the binding key is the UUID, not the name.
      2. ``title`` starts with ``"{staff.full_name}: {type_keyword}"``
         (case-insensitive). Catches legacy / manually-titled calendars and —
         critically — calendars created before the manager started writing
         the staff UUID into ``description``, which often hold the actual
         events while a separately-created UUID-stamped calendar is empty.
    """
    from django.db.models import Q

    staff_id_str = str(staff.id)
    staff_id_hex = staff_id_str.replace("-", "")
    # Anchor the type keyword to the ": " that parse_calendar_title expects
    # before the type. Plain icontains would substring-match the keyword
    # anywhere in the title — including inside a staff name (e.g. "Padmini"
    # contains "admin"), pulling the staff's Clinic calendar into the
    # admin-block lookup and silently zeroing out availability.
    qs = Calendar.objects.filter(
        (
            (Q(description__icontains=staff_id_str) | Q(description__icontains=staff_id_hex))
            & Q(title__icontains=f": {type_keyword}")
        )
        | Q(title__istartswith=f"{staff.full_name}: {type_keyword}")
    ).distinct()

    seen_ids: set = set()
    result: list = []
    for cal in qs:
        if cal.id in seen_ids:
            continue
        seen_ids.add(cal.id)
        result.append(cal)
    return result


def _resolve_staff(provider_id: str, staff_cache: dict | None):
    """Resolve a Staff object, optionally caching results across calls."""
    if staff_cache is not None and provider_id in staff_cache:
        return staff_cache[provider_id]
    try:
        staff = Staff.objects.get(id=provider_id)
    except Staff.DoesNotExist:
        staff = None
    if staff_cache is not None:
        staff_cache[provider_id] = staff
    return staff


def _resolve_calendars(staff, type_keyword: str, calendar_cache: dict | None):
    """Resolve the staff's calendars of the given type, with optional caching."""
    cache_key = (str(staff.id), type_keyword)
    if calendar_cache is not None and cache_key in calendar_cache:
        return calendar_cache[cache_key]
    cals = _staff_calendars(staff, type_keyword)
    if calendar_cache is not None:
        calendar_cache[cache_key] = cals
    return cals


def get_location_timezone(
    provider_id: str,
    location_name: str,
    staff_cache: dict | None = None,
    calendar_cache: dict | None = None,
) -> str:
    """Return the IANA timezone for the provider's calendar at the given location.

    Uses the same Staff lookup + Calendar title matching as get_availability_windows.
    Returns the timezone string from the first matching calendar, or "UTC".
    """
    staff = _resolve_staff(provider_id, staff_cache)
    if staff is None:
        log.warning("get_location_timezone: staff %s not found", provider_id)
        return "UTC"

    clinic_calendars = _resolve_calendars(staff, "Clinic", calendar_cache)

    for cal in clinic_calendars:
        _, cal_type, cal_location = parse_calendar_title(cal.title)

        if cal_location:
            if cal_location.strip().lower() != location_name.strip().lower():
                continue
        else:
            primary_loc = staff.primary_practice_location
            if not primary_loc:
                continue
            if primary_loc.full_name.strip().lower() != location_name.strip().lower():
                continue

        tz_name = str(cal.timezone) if cal.timezone else "UTC"
        return tz_name

    return "UTC"


def get_availability_windows(
    provider_id: str,
    location_name: str,
    target_date: str,
    staff_cache: dict | None = None,
    calendar_cache: dict | None = None,
) -> list[tuple[datetime.datetime, datetime.datetime]]:
    """Return availability windows for a provider at a location on a date.

    Looks up "Clinic" calendars whose title matches the provider and location,
    expands recurring events to the target date, and returns naive-local
    (start, end) tuples.
    """
    date_obj = datetime.date.fromisoformat(target_date)

    staff = _resolve_staff(provider_id, staff_cache)
    if staff is None:
        log.warning("get_availability_windows: staff %s not found", provider_id)
        return []

    staff_name = staff.full_name

    # Resilient lookup — match by staff UUID embedded in description first,
    # falling back to the legacy "{full_name}: Clinic" title prefix.
    clinic_calendars = _resolve_calendars(staff, "Clinic", calendar_cache)

    windows: list[tuple[datetime.datetime, datetime.datetime]] = []

    # Single query for all events across the matched calendars; group by the
    # calendar's primary key. NOTE: ``Calendar.id`` is a separate UUIDField,
    # NOT the primary key (canvas_sdk's IdentifiableModel keeps id as a
    # UUIDField but lets Django add its own auto-int pk). The FK column
    # ``Event.calendar_id`` stores the *pk*, so we MUST key on ``cal.pk``,
    # not ``cal.id`` — using ``cal.id`` here returns no matches.
    events_by_cal: dict = {}
    if clinic_calendars:
        for ev in Event.objects.filter(
            calendar__in=clinic_calendars, is_cancelled=False
        ):
            events_by_cal.setdefault(ev.calendar_id, []).append(ev)

    for cal in clinic_calendars:
        _, cal_type, cal_location = parse_calendar_title(cal.title)

        # Determine if this calendar applies to the requested location.
        if cal_location:
            if cal_location.strip().lower() != location_name.strip().lower():
                continue
        else:
            # No location in title — applies only to the provider's primary location.
            primary_loc = staff.primary_practice_location
            if not primary_loc:
                continue
            if primary_loc.full_name.strip().lower() != location_name.strip().lower():
                continue

        tz_name = str(cal.timezone) if cal.timezone else "UTC"
        try:
            calendar_tz = ZoneInfo(tz_name)
        except (KeyError, ValueError):
            calendar_tz = ZoneInfo("UTC")

        for event in events_by_cal.get(cal.pk, []):
            if event_occurs_on_date(event, date_obj):
                window = _event_window_on_date(event, date_obj, calendar_tz)
                if window:
                    windows.append(window)

    windows.sort(key=lambda w: w[0])

    log.info(
        "availability_windows: provider=%s (%s), location=%s, date=%s, %d windows: %s",
        provider_id,
        staff_name,
        location_name,
        target_date,
        len(windows),
        [(w[0].strftime("%H:%M"), w[1].strftime("%H:%M")) for w in windows],
    )

    return windows


def get_blocking_calendar_events(
    provider_id: str,
    target_date: str,
    calendar_tz: str = "",
    staff_cache: dict | None = None,
    calendar_cache: dict | None = None,
) -> list[tuple[datetime.datetime, datetime.datetime]]:
    """Return naive-local (start, end) windows for events on the provider's
    admin-style calendars on ``target_date``.

    A calendar is treated as admin/blocking when its title starts with the
    staff member's name AND contains "admin" (case-insensitive). Events on
    those calendars subtract from availability rather than open it — they're
    merged into the per-provider ``booked`` list used by the slot builders.

    Times are returned in the supplied ``calendar_tz`` so they line up with
    the availability windows and slot times.
    """
    try:
        date_obj = datetime.date.fromisoformat(target_date)
    except ValueError:
        return []

    staff = _resolve_staff(provider_id, staff_cache)
    if staff is None:
        return []

    staff_name = staff.full_name

    # Resilient lookup — match by staff UUID embedded in description first,
    # falling back to the legacy "{full_name} ... admin" title prefix.
    admin_calendars = _resolve_calendars(staff, "admin", calendar_cache)

    try:
        tz = ZoneInfo(calendar_tz) if calendar_tz else ZoneInfo("UTC")
    except (KeyError, ValueError):
        tz = ZoneInfo("UTC")

    blocks: list[tuple[datetime.datetime, datetime.datetime]] = []
    # Track the source calendar/event for each block so the log can pinpoint
    # which admin calendar is zeroing out availability (a real admin block vs.
    # a misclassified Clinic calendar).
    block_sources: list[
        tuple[datetime.datetime, datetime.datetime, str, Any, Any, str]
    ] = []
    # See note in get_availability_windows: keyed on cal.pk, not cal.id.
    events_by_cal: dict = {}
    if admin_calendars:
        for ev in Event.objects.filter(
            calendar__in=admin_calendars, is_cancelled=False
        ):
            events_by_cal.setdefault(ev.calendar_id, []).append(ev)
    log.info(
        "blocking_events: provider=%s (%s) matched %d admin calendar(s): %s",
        provider_id,
        staff_name,
        len(admin_calendars),
        [(str(c.id), c.title) for c in admin_calendars],
    )
    for cal in admin_calendars:
        for event in events_by_cal.get(cal.pk, []):
            if event_occurs_on_date(event, date_obj):
                window = _event_window_on_date(event, date_obj, tz)
                if window:
                    blocks.append(window)
                    block_sources.append(
                        (window[0], window[1], cal.title, cal.id, event.id, event.recurrence or "")
                    )

    blocks.sort(key=lambda w: w[0])
    block_sources.sort(key=lambda b: b[0])
    log.info(
        "blocking_events: provider=%s (%s), date=%s, %d admin blocks: %s",
        provider_id,
        staff_name,
        target_date,
        len(blocks),
        [
            (
                b[0].strftime("%H:%M"),
                b[1].strftime("%H:%M"),
                "calendar=%r calendar_id=%s event=%s rrule=%r" % (b[2], b[3], b[4], b[5]),
            )
            for b in block_sources
        ],
    )
    return blocks


def _fetch_clinic_calendars():
    return list(Calendar.objects.filter(title__icontains=": Clinic"))


def _fetch_schedulable_staff(schedulable_roles: list[str]):
    return list(
        Staff.objects.filter(
            active=True,
            roles__internal_code__in=schedulable_roles,
        )
        .exclude(roles__internal_code="RR")
        .distinct()
        .select_related("primary_practice_location")
    )


def get_providers_for_location(
    location_name: str,
    schedulable_roles: list[str],
    clinic_calendars: list | None = None,
    schedulable_staff: list | None = None,
) -> list[dict[str, str]]:
    """Return providers associated with a location based on Calendar data.

    A provider is associated with a location if they have a Clinic calendar
    that either:
      1. Explicitly names the location in the title, OR
      2. Has no location in the title AND their primary_practice_location
         matches the requested location.

    The candidate pool is active staff whose role codes intersect
    ``schedulable_roles`` (the ``SCHEDULABLE_STAFF_ROLES`` secret), excluding
    rooms (role ``RR``).

    Callers iterating multiple locations should pass pre-fetched
    ``clinic_calendars`` and ``schedulable_staff`` so this function makes no
    DB queries — that turns N location calls into a single pair of queries.
    """
    if clinic_calendars is None:
        clinic_calendars = _fetch_clinic_calendars()

    # Collect staff names that have a Clinic calendar for this location.
    names_with_location_calendar: set[str] = set()
    names_with_generic_clinic: set[str] = set()

    for cal in clinic_calendars:
        staff_name, cal_type, cal_location = parse_calendar_title(cal.title)
        if cal_type.strip().lower() != "clinic":
            continue

        if cal_location:
            if cal_location.strip().lower() == location_name.strip().lower():
                names_with_location_calendar.add(staff_name)
        else:
            names_with_generic_clinic.add(staff_name)

    # Candidate pool: active staff with at least one role in the configured
    # SCHEDULABLE_STAFF_ROLES, excluding rooms (RR appears via the
    # room-coordination logic, not in the provider dropdown).
    if schedulable_staff is None:
        all_schedulable = _fetch_schedulable_staff(schedulable_roles)
    else:
        all_schedulable = schedulable_staff

    result: list[dict[str, str]] = []
    seen_ids: set[str] = set()

    for staff in all_schedulable:
        sid = str(staff.id)
        if sid in seen_ids:
            continue

        name = staff.full_name

        # Match 1: explicit location calendar.
        if name in names_with_location_calendar:
            seen_ids.add(sid)
            result.append({"id": sid, "name": name})
            continue

        # Match 2: generic Clinic calendar + primary location matches.
        if name in names_with_generic_clinic:
            primary_loc = staff.primary_practice_location
            if (
                primary_loc
                and primary_loc.full_name.strip().lower()
                == location_name.strip().lower()
            ):
                seen_ids.add(sid)
                result.append({"id": sid, "name": name})

    log.info(
        "calendar providers: location=%s, %d with location calendar, "
        "%d with generic clinic, %d matched",
        location_name,
        len(names_with_location_calendar),
        len(names_with_generic_clinic),
        len(result),
    )

    return result
