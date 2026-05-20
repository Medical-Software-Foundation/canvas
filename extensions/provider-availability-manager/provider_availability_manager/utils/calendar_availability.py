"""Calendar-based availability: parse titles, expand RRULE, get availability windows."""

from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo

from canvas_sdk.v1.data.calendar import Calendar, Event
from canvas_sdk.v1.data.staff import Staff
from django.core.exceptions import ValidationError
from logger import log


# Map RRULE BYDAY abbreviations to Python weekday numbers (Monday=0).
_DAY_MAP = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def _sunday_of(d: datetime.date) -> datetime.date:
    """Return the Sunday on or before ``d``.

    Matches the JS frontend's ``weekStartOf`` in ``static/availability/main.js``
    (``s.setDate(s.getDate() - s.getDay())``), so WEEKLY+INTERVAL math agrees
    between the UI and the slot filter. Python's ``weekday()`` is 0..6 with
    Monday=0; Sunday=6, so we shift by ``(weekday() + 1) % 7`` to land on
    Sunday.
    """
    return d - datetime.timedelta(days=(d.weekday() + 1) % 7)


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


def event_occurs_on_date(
    event: Event,
    target_date: datetime.date,
    calendar_tz: ZoneInfo = ZoneInfo("UTC"),
) -> bool:
    """Check if a (possibly recurring) calendar event occurs on ``target_date``.

    ``Event.starts_at`` is stored as a tz-aware UTC datetime by canvas_sdk +
    Django USE_TZ. ``target_date`` is derived from the slot's *local* date by
    the slot filter. Calling ``.date()`` on the UTC datetime returns the UTC
    date, which can be one day off the calendar's local date for evening
    events in west-of-UTC zones (PST/MST/CST/EST) or morning events in
    positive-offset zones (Asia/Tokyo etc.). Convert to the calendar's
    timezone first so both sides of every comparison live in the same zone.

    ``calendar_tz`` defaults to UTC for backward compatibility with naive
    datetime fixtures in older tests. Production callers
    (``get_availability_windows``, ``get_blocking_calendar_events``) always
    pass the calendar's own timezone.
    """
    if not event.starts_at:
        return False

    # Naive datetimes are treated as already-local (older test fixtures);
    # aware datetimes are converted into the calendar's local zone.
    if event.starts_at.tzinfo is None:
        local_start_date = event.starts_at.date()
    else:
        local_start_date = event.starts_at.astimezone(calendar_tz).date()

    if not event.recurrence:
        return bool(local_start_date == target_date)

    # Event must have started on or before the target date.
    if target_date < local_start_date:
        return False

    rule = _parse_rrule(event.recurrence)
    freq = rule.get("FREQ", "")

    # UNTIL check.
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
        days_diff = (target_date - local_start_date).days
        return bool(days_diff % interval == 0)

    if freq == "WEEKLY":
        byday = rule.get("BYDAY", "")
        if byday:
            allowed_days = {
                _DAY_MAP[d.strip()]
                for d in byday.split(",")
                if d.strip() in _DAY_MAP
            }
            if target_date.weekday() not in allowed_days:
                return False

        if interval > 1:
            # Count Sunday-anchored calendar weeks, matching the JS UI's
            # ``weekStartOf`` (which shifts by ``getDay()`` to Sunday).
            # Rolling 7-day chunks from DTSTART would drift off the
            # calendar-week cadence whenever DTSTART falls on a weekday
            # other than the WKST anchor — so a Tuesday DTSTART with
            # BYDAY=MO,TH would invert every Monday's match relative to
            # what the UI displays.
            weeks_diff = (
                _sunday_of(target_date) - _sunday_of(local_start_date)
            ).days // 7
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

    Two DB lookups contribute, deduped by id:
      1. ``description`` contains the staff UUID (dashed or hex form).
         Resilient to staff renames because the binding key is the UUID,
         not the name.
      2. ``title`` starts with ``"{staff.full_name}: "``. Catches legacy
         or manually-titled calendars, including ones created before the
         manager started writing the staff UUID into ``description``.

    The ``type_keyword`` is then enforced in Python by parsing each title
    with ``parse_calendar_title`` and comparing the parsed type field
    exactly (case-insensitive). The previous implementation scoped the
    type at the DB layer with ``title__icontains=": {type_keyword}"`` —
    but a documented title is ``"{Name}: {Type}: {Location}"``, so that
    substring also matched ``": admin"`` *inside* a location name
    (e.g. ``"Dr Smith: Clinic: Admin Office"``). Such a Clinic calendar
    would be pulled into the admin-block lookup, its events would
    subtract from the windows they produce, and the provider's slots
    would silently zero out at every location. Filtering on the parsed
    type field closes that off because the parser distinguishes the type
    slot from the location slot.
    """
    from django.db.models import Q

    staff_id_str = str(staff.id)
    staff_id_hex = staff_id_str.replace("-", "")
    qs = Calendar.objects.filter(
        Q(description__icontains=staff_id_str)
        | Q(description__icontains=staff_id_hex)
        | Q(title__istartswith=f"{staff.full_name}: ")
    ).distinct()

    keyword_lower = type_keyword.strip().lower()
    seen_ids: set = set()
    result: list = []
    for cal in qs:
        if cal.id in seen_ids:
            continue
        _, cal_type, _ = parse_calendar_title(cal.title or "")
        if cal_type.strip().lower() != keyword_lower:
            continue
        seen_ids.add(cal.id)
        result.append(cal)
    return result


def _resolve_staff(provider_id: str, staff_cache: dict | None):
    """Resolve a Staff object, optionally caching results across calls.

    ``Staff.id`` is a UUIDField — Django raises ``ValidationError`` during
    query construction for non-UUID input. ``provider_id`` ultimately comes
    from the undocumented ``selected_values`` / ``slots_by_provider`` payload
    on ``APPOINTMENT__SLOTS__POST_SEARCH``; if a non-UUID value sneaks
    through, letting the exception propagate would crash ``compute()``,
    suppress the filter effect entirely, and silently flip the fail-closed
    handler into fail-OPEN. Treat malformed input the same as a missing
    Staff and return None.
    """
    if staff_cache is not None and provider_id in staff_cache:
        return staff_cache[provider_id]
    try:
        staff = Staff.objects.get(id=provider_id)
    except (Staff.DoesNotExist, ValueError, ValidationError):
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
            if event_occurs_on_date(event, date_obj, calendar_tz):
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
    # See note in get_availability_windows: keyed on cal.pk, not cal.id.
    events_by_cal: dict = {}
    if admin_calendars:
        for ev in Event.objects.filter(
            calendar__in=admin_calendars, is_cancelled=False
        ):
            events_by_cal.setdefault(ev.calendar_id, []).append(ev)
    for cal in admin_calendars:
        for event in events_by_cal.get(cal.pk, []):
            if event_occurs_on_date(event, date_obj, tz):
                window = _event_window_on_date(event, date_obj, tz)
                if window:
                    blocks.append(window)

    blocks.sort(key=lambda w: w[0])
    log.info(
        "blocking_events: provider=%s (%s), date=%s, %d admin blocks: %s",
        provider_id,
        staff_name,
        target_date,
        len(blocks),
        [(b[0].strftime("%H:%M"), b[1].strftime("%H:%M")) for b in blocks],
    )
    return blocks


