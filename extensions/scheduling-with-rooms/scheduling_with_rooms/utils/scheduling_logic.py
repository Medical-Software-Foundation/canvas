"""Scheduling logic: generate available slots from calendar availability minus existing appointments."""

from __future__ import annotations

import datetime
from typing import Any
from zoneinfo import ZoneInfo

from canvas_sdk.v1.data.appointment import Appointment, AppointmentProgressStatus
from canvas_sdk.v1.data.staff import Staff
from logger import log

from scheduling_with_rooms.models import get_concurrent_limit, prefetch_concurrent_limits
from scheduling_with_rooms.utils.calendar_availability import (
    get_availability_windows,
    get_blocking_calendar_events,
)


DEFAULT_DURATION_MINUTES = 20

# Appointment statuses that should NOT block a time slot. Use the SDK
# enum so the canonical strings stay in one place — Canvas's column stores
# "noshowed" (not "noshow"), and "entered-in-error" is a FHIR-spec value
# the internal column never produces.
_NON_BLOCKING_STATUSES = (
    AppointmentProgressStatus.CANCELLED,
    AppointmentProgressStatus.NOSHOWED,
)

# How often a provider slot may start within an availability window.
SLOT_STEP_MINUTES = 30


def _count_overlaps(
    slot_start: datetime.datetime,
    slot_end: datetime.datetime,
    booked: list[tuple[datetime.datetime, datetime.datetime]],
) -> int:
    """Count booked appointments overlapping the slot."""
    count = 0
    for a_start, a_end in booked:
        s = a_start.replace(tzinfo=None) if a_start.tzinfo else a_start
        e = a_end.replace(tzinfo=None) if a_end.tzinfo else a_end
        if slot_start < e and slot_end > s:
            count += 1
    return count


def _subtract_blocks(
    windows: list[tuple[datetime.datetime, datetime.datetime]],
    blocks: list[tuple[datetime.datetime, datetime.datetime]],
) -> list[tuple[datetime.datetime, datetime.datetime]]:
    """Return ``windows`` with ``blocks`` carved out.

    For each input window, overlapping blocks are removed, leaving zero or
    more sub-windows representing the time the resource is actually free.
    """
    result: list[tuple[datetime.datetime, datetime.datetime]] = []
    for win_start, win_end in windows:
        win_blocks = sorted(
            [
                (max(b[0], win_start), min(b[1], win_end))
                for b in blocks
                if b[0] < win_end and b[1] > win_start
            ],
            key=lambda x: x[0],
        )
        cursor = win_start
        for block_start, block_end in win_blocks:
            if cursor < block_start:
                result.append((cursor, block_start))
            if block_end > cursor:
                cursor = block_end
        if cursor < win_end:
            result.append((cursor, win_end))
    return result


def _generate_time_slots_from_windows(
    windows: list[tuple[datetime.datetime, datetime.datetime]],
    duration_minutes: int,
    step_minutes: int = SLOT_STEP_MINUTES,
) -> list[tuple[datetime.datetime, datetime.datetime]]:
    """Generate (start, end) slot tuples within the given availability windows.

    ``step_minutes`` controls how often a slot can start within a window:
    - Providers default to 30 min (fine-grained start times).
    - Rooms pass ``step_minutes=duration_minutes`` so each window yields only
      duration-aligned slots — a 9 h room window with a 180-min appointment
      gives {9, 12, 15} instead of every 30 min.
    """
    delta = datetime.timedelta(minutes=duration_minutes)
    step = datetime.timedelta(minutes=step_minutes)
    slots: list[tuple[datetime.datetime, datetime.datetime]] = []
    for win_start, win_end in windows:
        current = win_start
        while current + delta <= win_end:
            slots.append((current, current + delta))
            current += step
    return slots


# Widen appointment query windows to cover any UTC offset (up to ±14 h).
_UTC_OFFSET_BUFFER = datetime.timedelta(hours=16)


def _to_calendar_local(
    start: datetime.datetime, tz: ZoneInfo | None
) -> datetime.datetime:
    """Drop an appointment's UTC start into naive calendar-local time."""
    if tz and start.tzinfo:
        return start.astimezone(tz).replace(tzinfo=None)
    if start.tzinfo:
        return start.replace(tzinfo=None)
    return start


def prefetch_blocking_appointments(
    staff_ids: list[str],
    range_start: datetime.datetime,
    range_end: datetime.datetime,
    calendar_tz: str = "",
) -> dict[str, list[tuple[datetime.datetime, datetime.datetime]]]:
    """Fetch blocking appointments for many staff over a whole range, in one query.

    Callers that sweep a date range (the month view) would otherwise run one
    query per staff member per day. The returned windows are naive
    calendar-local, matching what :func:`_get_blocking_appointments` produces,
    and are meant to be passed back in as its ``booked_cache``.
    """
    ids = [staff_id for staff_id in dict.fromkeys(staff_ids) if staff_id]
    if not ids:
        return {}

    rows = (
        Appointment.objects.filter(
            provider__id__in=ids,
            start_time__lt=range_end + _UTC_OFFSET_BUFFER,
            start_time__gte=range_start - _UTC_OFFSET_BUFFER,
        )
        .exclude(status__in=_NON_BLOCKING_STATUSES)
        .values_list("provider__id", "start_time", "duration_minutes")
    )

    tz = ZoneInfo(calendar_tz) if calendar_tz else None
    by_staff: dict[str, list[tuple[datetime.datetime, datetime.datetime]]] = {
        staff_id: [] for staff_id in ids
    }
    for staff_id, start, duration in rows:
        if not start or not duration:
            continue
        local_start = _to_calendar_local(start, tz)
        by_staff.setdefault(str(staff_id), []).append(
            (local_start, local_start + datetime.timedelta(minutes=duration))
        )

    log.info(
        "prefetch_blocking_appts: %d staff, %s..%s, %d blocking appts",
        len(ids), range_start.date(), range_end.date(),
        sum(len(v) for v in by_staff.values()),
    )
    return by_staff


def _get_blocking_appointments(
    provider_id: str,
    day_start: datetime.datetime,
    day_end: datetime.datetime,
    calendar_tz: str = "",
    booked_cache: dict[str, list[tuple[datetime.datetime, datetime.datetime]]] | None = None,
) -> list[tuple[datetime.datetime, datetime.datetime]]:
    """Return (start, end) tuples of existing appointments that block slots.

    The Appointment model has ``start_time`` and ``duration_minutes`` but no
    ``end_time`` column, so we compute the end from those two fields.

    Appointments are stored in UTC.  Slot times are naive in the calendar's
    local timezone.  We widen the query window to account for the UTC offset
    and convert returned times to the calendar's local timezone so overlap
    checks work correctly.

    Uses a blacklist approach: all appointments block EXCEPT explicitly
    non-blocking statuses (cancelled, noshowed).

    ``booked_cache`` — from :func:`prefetch_blocking_appointments` — replaces
    the query with an in-memory filter, for callers sweeping many days.
    """
    if booked_cache is not None:
        return [
            (start, end)
            for start, end in booked_cache.get(provider_id, ())
            if end > day_start and start < day_end
        ]

    appts = list(
        Appointment.objects.filter(
            provider__id=provider_id,
            start_time__lt=day_end + _UTC_OFFSET_BUFFER,
            start_time__gte=day_start - _UTC_OFFSET_BUFFER,
        )
        .exclude(status__in=_NON_BLOCKING_STATUSES)
        .values_list("start_time", "duration_minutes", "status")
    )

    tz = ZoneInfo(calendar_tz) if calendar_tz else None

    result: list[tuple[datetime.datetime, datetime.datetime]] = []
    for start, duration, _status in appts:
        if start and duration:
            local_start = _to_calendar_local(start, tz)
            end = local_start + datetime.timedelta(minutes=duration)
            if end > day_start and local_start < day_end:
                result.append((local_start, end))
    return result


def _slot_in_windows(
    slot_start: datetime.datetime,
    slot_end: datetime.datetime,
    windows: list[tuple[datetime.datetime, datetime.datetime]],
) -> bool:
    """Return True if the slot fits entirely within at least one window."""
    for win_start, win_end in windows:
        if slot_start >= win_start and slot_end <= win_end:
            return True
    return False


def build_plain_slots(
    provider_id: str,
    location_id: str,
    date: str,
    duration_minutes: int,
    location_name: str = "",
    calendar_tz: str = "",
    staff_cache: dict | None = None,
    calendar_cache: dict | None = None,
    booked_cache: dict | None = None,
    limit_cache: dict | None = None,
) -> list[dict[str, Any]]:
    """Generate available slots from calendar availability minus existing appointments.

    Honors the per-staff concurrent-slot limit configured in the admin app
    (default 1: any overlap blocks the slot).
    """
    windows = get_availability_windows(
        provider_id, location_name, date,
        staff_cache=staff_cache, calendar_cache=calendar_cache,
    )
    time_slots = _generate_time_slots_from_windows(windows, duration_minutes)

    if not time_slots:
        return []

    day_start = time_slots[0][0]
    day_end = time_slots[-1][1]
    booked = _get_blocking_appointments(
        provider_id, day_start, day_end, calendar_tz, booked_cache=booked_cache
    )
    hard_blocks = get_blocking_calendar_events(
        provider_id, date, calendar_tz,
        staff_cache=staff_cache, calendar_cache=calendar_cache,
    )
    concurrent_limit = get_concurrent_limit(provider_id, cache=limit_cache)
    log.info(
        "slots: provider=%s, date=%s, %d candidate slots, %d booked, %d hard blocks, concurrent_limit=%d",
        provider_id, date, len(time_slots), len(booked), len(hard_blocks), concurrent_limit,
    )

    result: list[dict[str, Any]] = []
    for slot_start, slot_end in time_slots:
        if _count_overlaps(slot_start, slot_end, hard_blocks) > 0:
            continue
        if _count_overlaps(slot_start, slot_end, booked) < concurrent_limit:
            result.append({
                "start": slot_start.isoformat(),
                "end": slot_end.isoformat(),
            })
    return result


def build_all_provider_slots(
    provider_list: list[dict[str, str]],
    location_id: str,
    date: str,
    duration_minutes: int,
    location_name: str = "",
    calendar_tz: str = "",
    staff_cache: dict | None = None,
    calendar_cache: dict | None = None,
    booked_cache: dict | None = None,
    limit_cache: dict | None = None,
) -> list[dict[str, Any]]:
    """Build available slots for every provider on a single date.

    Args:
        provider_list: ``[{id, name}]`` from ``get_providers_for_location``.
        location_id: Practice location UUID.
        date: Target date (``YYYY-MM-DD``).
        duration_minutes: Slot length in minutes.
        location_name: Human-readable location name for calendar matching.
        calendar_tz: IANA timezone string for the location calendar.
        staff_cache, calendar_cache, booked_cache, limit_cache: optional shared
            caches. Callers building several locations in one request should
            pass all four so the underlying queries are made once overall
            rather than once per location.

    Returns:
        ``[{id, name, slots: [{start, end}]}]`` — one entry per provider.
    """
    if staff_cache is None:
        staff_cache = {}
    if calendar_cache is None:
        calendar_cache = {}
    # One query each for appointments and limits across every provider, rather
    # than a pair per provider.
    provider_ids = [prov["id"] for prov in provider_list]
    if limit_cache is None:
        limit_cache = prefetch_concurrent_limits(provider_ids)
    if booked_cache is None:
        booked_cache = prefetch_blocking_appointments(
            provider_ids,
            datetime.datetime.fromisoformat(date),
            datetime.datetime.fromisoformat(date) + datetime.timedelta(days=1),
            calendar_tz,
        )
    result: list[dict[str, Any]] = []
    for prov in provider_list:
        slots = build_plain_slots(
            provider_id=prov["id"],
            location_id=location_id,
            date=date,
            duration_minutes=duration_minutes,
            location_name=location_name,
            calendar_tz=calendar_tz,
            staff_cache=staff_cache,
            calendar_cache=calendar_cache,
            booked_cache=booked_cache,
            limit_cache=limit_cache,
        )
        result.append({
            "id": prov["id"],
            "name": prov["name"],
            "slots": slots,
        })
    return result


def build_month_slot_counts(
    provider_list: list[dict[str, str]],
    year: int,
    month: int,
    duration_minutes: int,
    location_name: str = "",
    calendar_tz: str = "",
    allowed_room_keys: set[str] | None = None,
) -> dict[str, int]:
    """Count bookable slots per day for a calendar month.

    Returns ``{"2026-03-01": 12, "2026-03-02": 0, ...}`` for every day
    in the given month.

    When ``allowed_room_keys`` is provided (the visit type requires a room),
    a slot only counts if at least one allowed room is also free at the same
    start time — otherwise the day shows green here but the day view says
    "No availability".
    """
    # Next month's day-0 gives last day of current month.
    days_in_month = (datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)).day if month < 12 else 31
    counts: dict[str, int] = {}
    # Per-request caches: same staff/calendars are looked up across all 31
    # days × P providers, so resolve each only once.
    staff_cache: dict = {}
    calendar_cache: dict = {}

    # Appointments and concurrent limits are month-wide facts, so fetch them
    # once here rather than per day per staff member — that was 31 × P queries
    # for each, and dominated the cost of rendering the month view.
    provider_ids = [prov["id"] for prov in provider_list]
    room_staff = resolve_room_staff(allowed_room_keys) if allowed_room_keys is not None else []
    room_ids = [str(rr.id) for rr in room_staff]
    limit_cache = prefetch_concurrent_limits(provider_ids + room_ids)
    booked_cache = prefetch_blocking_appointments(
        provider_ids + room_ids,
        datetime.datetime(year, month, 1),
        datetime.datetime(year, month, days_in_month) + datetime.timedelta(days=1),
        calendar_tz,
    )

    for day in range(1, days_in_month + 1):
        date_str = f"{year}-{month:02d}-{day:02d}"

        # Compute room start-times for this day if rooms are required.
        room_starts: set[str] | None = None
        if allowed_room_keys is not None:
            rooms_data = build_all_room_slots(
                date=date_str,
                duration_minutes=duration_minutes,
                location_name=location_name,
                calendar_tz=calendar_tz,
                allowed_room_keys=allowed_room_keys,
                staff_cache=staff_cache,
                calendar_cache=calendar_cache,
                booked_cache=booked_cache,
                limit_cache=limit_cache,
                room_staff=room_staff,
            )
            room_starts = set()
            for room in rooms_data:
                for s in room.get("slots", []):
                    room_starts.add(s["start"])

        total = 0
        for prov in provider_list:
            slots = build_plain_slots(
                provider_id=prov["id"],
                location_id="",
                date=date_str,
                duration_minutes=duration_minutes,
                location_name=location_name,
                calendar_tz=calendar_tz,
                staff_cache=staff_cache,
                calendar_cache=calendar_cache,
                booked_cache=booked_cache,
                limit_cache=limit_cache,
            )
            if room_starts is None:
                total += len(slots)
            else:
                total += sum(1 for s in slots if s["start"] in room_starts)
        counts[date_str] = total
    return counts


def resolve_room_staff(allowed_room_keys: set[str] | None = None) -> list:
    """Return the active RR-role Staff rows eligible as rooms.

    Extracted so callers sweeping many dates can resolve rooms once and hand
    the list back in, instead of re-running this query per day.
    """
    rr_qs = Staff.objects.filter(active=True, roles__internal_code="RR").distinct()
    if allowed_room_keys is not None:
        rr_qs = rr_qs.filter(id__in=allowed_room_keys)
    return list(rr_qs)


def build_all_room_slots(
    date: str,
    duration_minutes: int,
    location_name: str = "",
    calendar_tz: str = "",
    allowed_room_keys: set[str] | None = None,
    staff_cache: dict | None = None,
    calendar_cache: dict | None = None,
    booked_cache: dict | None = None,
    limit_cache: dict | None = None,
    room_staff: list | None = None,
) -> list[dict[str, Any]]:
    """Build available slots for every active RR staff member on a single date.

    Each RR staff's per-room concurrent-slot limit comes from the admin app
    (default 1).

    Args:
        date: Target date (``YYYY-MM-DD``).
        duration_minutes: Slot length in minutes.
        location_name: Human-readable location name for calendar matching.
        calendar_tz: IANA timezone string for the location calendar.
        allowed_room_keys: Optional set of RR staff IDs to limit to. ``None``
            means all active RR staff. The visit-type → room admin matrix
            populates this set per appointment type.

    Returns:
        ``[{id, name, slots: [{start, end}]}]`` — one entry per RR staff.
    """
    rr_staff_list = room_staff if room_staff is not None else resolve_room_staff(allowed_room_keys)
    if not rr_staff_list:
        return []

    # Per-call caches default to fresh dicts when not supplied by the caller.
    if staff_cache is None:
        staff_cache = {}
    if calendar_cache is None:
        calendar_cache = {}
    rr_ids = [str(rr.id) for rr in rr_staff_list]
    if limit_cache is None:
        limit_cache = prefetch_concurrent_limits(rr_ids)
    if booked_cache is None:
        booked_cache = prefetch_blocking_appointments(
            rr_ids,
            datetime.datetime.fromisoformat(date),
            datetime.datetime.fromisoformat(date) + datetime.timedelta(days=1),
            calendar_tz,
        )
    result: list[dict[str, Any]] = []
    delta = datetime.timedelta(minutes=duration_minutes)
    for rr in rr_staff_list:
        rr_id = str(rr.id)
        # Avoid the duplicate Staff.get for an RR we already resolved.
        staff_cache.setdefault(rr_id, rr)
        windows = get_availability_windows(
            rr_id, location_name, date,
            staff_cache=staff_cache, calendar_cache=calendar_cache,
        )
        if not windows:
            result.append({"id": rr_id, "name": rr.full_name, "slots": []})
            continue

        hard_blocks = get_blocking_calendar_events(
            rr_id, date, calendar_tz,
            staff_cache=staff_cache, calendar_cache=calendar_cache,
        )
        # Subtract hard blocks from the room's window, then start each free
        # sub-window's first slot at the earliest available time inside it
        # (i.e. the post-block boundary) and advance by duration. So a window
        # of (08:00, 17:00) with a (08:00, 08:30) block becomes (08:30, 11:30)
        # → slots 08:30 and 10:00 for a 90-min appointment.
        effective_windows = _subtract_blocks(windows, hard_blocks)
        time_slots: list[tuple[datetime.datetime, datetime.datetime]] = []
        for win_start, win_end in effective_windows:
            current = win_start
            while current + delta <= win_end:
                time_slots.append((current, current + delta))
                current += delta

        if not time_slots:
            result.append({"id": rr_id, "name": rr.full_name, "slots": []})
            continue

        day_start = time_slots[0][0]
        day_end = time_slots[-1][1]
        booked = _get_blocking_appointments(
            rr_id, day_start, day_end, calendar_tz, booked_cache=booked_cache
        )
        concurrent_limit = get_concurrent_limit(rr_id, cache=limit_cache)

        free_slots: list[dict[str, str]] = []
        for slot_start, slot_end in time_slots:
            # hard_blocks were already subtracted from the windows above, so
            # only the booked-appointments check remains here.
            if _count_overlaps(slot_start, slot_end, booked) < concurrent_limit:
                free_slots.append({
                    "start": slot_start.isoformat(),
                    "end": slot_end.isoformat(),
                })

        result.append({"id": rr_id, "name": rr.full_name, "slots": free_slots})
    return result
