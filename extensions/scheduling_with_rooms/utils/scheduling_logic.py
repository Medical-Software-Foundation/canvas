"""Scheduling logic: generate available slots from calendar availability minus existing appointments."""

from __future__ import annotations

import datetime
from typing import Any
from zoneinfo import ZoneInfo

from canvas_sdk.v1.data.appointment import Appointment
from canvas_sdk.v1.data.staff import Staff
from logger import log

from scheduling_with_rooms.models import get_concurrent_limit
from scheduling_with_rooms.utils.calendar_availability import (
    get_availability_windows,
    get_blocking_calendar_events,
)


DEFAULT_DURATION_MINUTES = 20

# Default business hours (8 AM to 5 PM) — fallback only.
DEFAULT_START_HOUR = 8
DEFAULT_END_HOUR = 17

# Appointment statuses that should NOT block a time slot.
_NON_BLOCKING_STATUSES = ("cancelled", "noshow", "entered-in-error")


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


def _generate_time_slots(
    date: str,
    duration_minutes: int,
    start_hour: int = DEFAULT_START_HOUR,
    end_hour: int = DEFAULT_END_HOUR,
) -> list[tuple[datetime.datetime, datetime.datetime]]:
    """Generate (start, end) tuples for every slot in the business day."""
    base = datetime.datetime.fromisoformat(f"{date}T00:00:00")
    day_start = base.replace(hour=start_hour, minute=0, second=0)
    day_end = base.replace(hour=end_hour, minute=0, second=0)
    delta = datetime.timedelta(minutes=duration_minutes)

    slots: list[tuple[datetime.datetime, datetime.datetime]] = []
    current = day_start
    while current + delta <= day_end:
        slots.append((current, current + delta))
        current += delta
    return slots


SLOT_STEP_MINUTES = 30


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


def _get_blocking_appointments(
    provider_id: str,
    day_start: datetime.datetime,
    day_end: datetime.datetime,
    calendar_tz: str = "",
) -> list[tuple[datetime.datetime, datetime.datetime]]:
    """Return (start, end) tuples of existing appointments that block slots.

    The Appointment model has ``start_time`` and ``duration_minutes`` but no
    ``end_time`` column, so we compute the end from those two fields.

    Appointments are stored in UTC.  Slot times are naive in the calendar's
    local timezone.  We widen the query window to account for the UTC offset
    and convert returned times to the calendar's local timezone so overlap
    checks work correctly.

    Uses a blacklist approach: all appointments block EXCEPT explicitly
    non-blocking statuses (cancelled, noshow, entered-in-error).
    """
    # Widen the query window to cover any UTC offset (up to ±14 h).
    buffer = datetime.timedelta(hours=16)
    appts = list(
        Appointment.objects.filter(
            provider__id=provider_id,
            start_time__lt=day_end + buffer,
            start_time__gte=day_start - buffer,
        )
        .exclude(status__in=_NON_BLOCKING_STATUSES)
        .values_list("start_time", "duration_minutes", "status")
    )

    log.info(
        "blocking_appts: provider=%s, found %d appts, statuses=%s",
        provider_id,
        len(appts),
        [a[2] for a in appts],
    )

    tz = ZoneInfo(calendar_tz) if calendar_tz else None

    result: list[tuple[datetime.datetime, datetime.datetime]] = []
    for start, duration, _status in appts:
        if start and duration:
            # Convert from UTC to the calendar's local timezone.
            if tz and start.tzinfo:
                start = start.astimezone(tz).replace(tzinfo=None)
            elif start.tzinfo:
                start = start.replace(tzinfo=None)
            end = start + datetime.timedelta(minutes=duration)
            if end > day_start and start < day_end:
                result.append((start, end))
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
    booked = _get_blocking_appointments(provider_id, day_start, day_end, calendar_tz)
    hard_blocks = get_blocking_calendar_events(
        provider_id, date, calendar_tz,
        staff_cache=staff_cache, calendar_cache=calendar_cache,
    )
    concurrent_limit = get_concurrent_limit(provider_id)
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
) -> list[dict[str, Any]]:
    """Build available slots for every provider on a single date.

    Args:
        provider_list: ``[{id, name}]`` from ``get_providers_for_location``.
        location_id: Practice location UUID.
        date: Target date (``YYYY-MM-DD``).
        duration_minutes: Slot length in minutes.
        location_name: Human-readable location name for calendar matching.
        calendar_tz: IANA timezone string for the location calendar.

    Returns:
        ``[{id, name, slots: [{start, end}]}]`` — one entry per provider.
    """
    staff_cache: dict = {}
    calendar_cache: dict = {}
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
            )
            if room_starts is None:
                total += len(slots)
            else:
                total += sum(1 for s in slots if s["start"] in room_starts)
        counts[date_str] = total
    return counts


def build_all_room_slots(
    date: str,
    duration_minutes: int,
    location_name: str = "",
    calendar_tz: str = "",
    allowed_room_keys: set[str] | None = None,
    staff_cache: dict | None = None,
    calendar_cache: dict | None = None,
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
    rr_qs = Staff.objects.filter(active=True, roles__internal_code="RR").distinct()
    if allowed_room_keys is not None:
        rr_qs = rr_qs.filter(id__in=allowed_room_keys)
    rr_staff_list = list(rr_qs)
    if not rr_staff_list:
        return []

    # Per-call caches default to fresh dicts when not supplied by the caller.
    if staff_cache is None:
        staff_cache = {}
    if calendar_cache is None:
        calendar_cache = {}
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
        booked = _get_blocking_appointments(rr_id, day_start, day_end, calendar_tz)
        concurrent_limit = get_concurrent_limit(rr_id)

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


def build_slots_with_resource_availability(
    provider_id: str,
    location_id: str,
    date: str,
    duration_minutes: int,
    location_name: str = "",
    calendar_tz: str = "",
    allowed_room_keys: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Generate slots with RR staff availability annotation.

    For each candidate slot, checks the provider and every eligible RR
    staff member. Each staff member's per-staff concurrent-slot limit
    (admin app) governs whether their bookings block the slot.

    Both regular Appointments and room ScheduleEvents are stored in the
    Canvas Appointment data model, so a single DB query catches both.

    Slots with no available RR staff are excluded.
    """
    # Per-request caches shared across the provider + every RR staff member.
    staff_cache: dict = {}
    calendar_cache: dict = {}
    windows = get_availability_windows(
        provider_id, location_name, date,
        staff_cache=staff_cache, calendar_cache=calendar_cache,
    )
    time_slots = _generate_time_slots_from_windows(windows, duration_minutes)

    if not time_slots:
        return []

    day_start = time_slots[0][0]
    day_end = time_slots[-1][1]
    provider_booked = _get_blocking_appointments(provider_id, day_start, day_end, calendar_tz)
    provider_hard_blocks = get_blocking_calendar_events(
        provider_id, date, calendar_tz,
        staff_cache=staff_cache, calendar_cache=calendar_cache,
    )
    provider_limit = get_concurrent_limit(provider_id)

    rr_qs = Staff.objects.filter(active=True, roles__internal_code="RR").distinct()
    if allowed_room_keys is not None:
        rr_qs = rr_qs.filter(id__in=allowed_room_keys)
    rr_staff_list = list(rr_qs)
    log.info(
        "slots (RR): provider=%s, date=%s, %d candidate slots, %d RR staff, provider_limit=%d",
        provider_id, date, len(time_slots), len(rr_staff_list), provider_limit,
    )

    if not rr_staff_list:
        return []

    # Pre-fetch calendar availability, bookings, hard blocks, and concurrent limit per RR.
    rr_windows: dict[str, list[tuple[datetime.datetime, datetime.datetime]]] = {}
    rr_booked: dict[str, list[tuple[datetime.datetime, datetime.datetime]]] = {}
    rr_hard_blocks: dict[str, list[tuple[datetime.datetime, datetime.datetime]]] = {}
    rr_limit: dict[str, int] = {}
    for rr in rr_staff_list:
        rr_id = str(rr.id)
        staff_cache.setdefault(rr_id, rr)
        rr_windows[rr_id] = get_availability_windows(
            rr_id, location_name, date,
            staff_cache=staff_cache, calendar_cache=calendar_cache,
        )
        rr_booked[rr_id] = _get_blocking_appointments(
            rr_id, day_start, day_end, calendar_tz,
        )
        rr_hard_blocks[rr_id] = get_blocking_calendar_events(
            rr_id, date, calendar_tz,
            staff_cache=staff_cache, calendar_cache=calendar_cache,
        )
        rr_limit[rr_id] = get_concurrent_limit(rr_id)

    result: list[dict[str, Any]] = []
    for slot_start, slot_end in time_slots:
        # Provider hard blocks (admin events) trump capacity entirely.
        if _count_overlaps(slot_start, slot_end, provider_hard_blocks) > 0:
            continue
        # Provider must have capacity for the slot.
        if _count_overlaps(slot_start, slot_end, provider_booked) >= provider_limit:
            continue

        available_rr: list[dict[str, str]] = []
        for rr in rr_staff_list:
            rr_id = str(rr.id)

            # RR staff must have calendar availability for this slot.
            if not _slot_in_windows(slot_start, slot_end, rr_windows.get(rr_id, [])):
                continue

            # RR hard blocks trump capacity entirely.
            if _count_overlaps(slot_start, slot_end, rr_hard_blocks.get(rr_id, [])) > 0:
                continue

            if _count_overlaps(slot_start, slot_end, rr_booked.get(rr_id, [])) < rr_limit[rr_id]:
                available_rr.append({"id": rr_id, "name": rr.full_name})

        if available_rr:
            result.append({
                "start": slot_start.isoformat(),
                "end": slot_end.isoformat(),
                "available_rr_staff": available_rr,
            })

    return result
