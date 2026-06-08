import datetime
from typing import Any
from zoneinfo import ZoneInfo

_DAY_INDEX = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}

# Appointment status values that should NOT block a slot. Anything else (confirmed,
# unconfirmed, arrived, roomed, etc.) blocks. Lowercase strings to match the values
# the ORM stores for `Appointment.status`.
_NON_BLOCKING_APPOINTMENT_STATUSES = ("cancelled", "noshow", "entered-in-error")

# Buffer to absorb timezone offset when querying appointments by a window.
_APPOINTMENT_QUERY_BUFFER = datetime.timedelta(hours=16)


def parse_calendar_title(title: str) -> tuple[str, str, str | None]:
    parts = title.split(":", 2)
    if len(parts) == 3:
        return parts[0].strip(), parts[1].strip(), parts[2].strip()
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip(), None
    return parts[0].strip(), "", None


def _align_slot_start(dt: datetime.datetime, duration_minutes: int) -> datetime.datetime:
    """Round `dt` UP to the next multiple of `duration_minutes` from midnight.

    This gives patient-friendly wall-clock slot times (e.g. 1:30 PM rather than
    1:25 PM) regardless of how the underlying availability event was scheduled.
    """
    midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed_seconds = int((dt - midnight).total_seconds())
    duration_seconds = duration_minutes * 60
    # Ceiling division for ints: -(-a // b)
    blocks = -(-elapsed_seconds // duration_seconds)
    return midnight + datetime.timedelta(minutes=blocks * duration_minutes)


def chunk_window_into_slots(
    windows: list[tuple[datetime.datetime, datetime.datetime]],
    duration_minutes: int,
) -> list[tuple[datetime.datetime, datetime.datetime]]:
    delta = datetime.timedelta(minutes=duration_minutes)
    slots: list[tuple[datetime.datetime, datetime.datetime]] = []
    seen_starts: set[datetime.datetime] = set()
    for window_start, window_end in windows:
        cursor = _align_slot_start(window_start, duration_minutes)
        while cursor + delta <= window_end:
            # Overlapping availability events can chunk to the same start time;
            # emit each distinct start once so the patient never sees duplicate slots.
            if cursor not in seen_starts:
                seen_starts.add(cursor)
                slots.append((cursor, cursor + delta))
            cursor += delta
    return slots


def filter_free_slots(
    slots: list[tuple[datetime.datetime, datetime.datetime]],
    booked: list[tuple[datetime.datetime, datetime.datetime]],
) -> list[tuple[datetime.datetime, datetime.datetime]]:
    # Half-open interval overlap: slot [s_start, s_end) collides with
    # booked [b_start, b_end) iff s_start < b_end and s_end > b_start.
    return [
        (s_start, s_end)
        for s_start, s_end in slots
        if all(s_start >= b_end or s_end <= b_start for b_start, b_end in booked)
    ]


def apply_lead_time(
    slots: list[tuple[datetime.datetime, datetime.datetime]],
    *,
    now: datetime.datetime,
    lead_time_minutes: int,
) -> list[tuple[datetime.datetime, datetime.datetime]]:
    threshold = now + datetime.timedelta(minutes=lead_time_minutes)
    return [(start, end) for start, end in slots if start >= threshold]


def _parse_rrule(rrule: str) -> dict[str, str]:
    body = rrule.removeprefix("RRULE:")
    out: dict[str, str] = {}
    for part in body.split(";"):
        if "=" in part:
            key, value = part.split("=", 1)
            out[key] = value
    return out


def _parse_until(until: str) -> datetime.date | None:
    # Canvas serializes UNTIL as YYYYMMDDTHHMMSS or YYYYMMDDTHHMMSSZ (UTC).
    trimmed = until.rstrip("Z")
    try:
        return datetime.datetime.strptime(trimmed[:15], "%Y%m%dT%H%M%S").date()
    except ValueError:
        return None


def _week_start(d: datetime.date, wkst_weekday: int) -> datetime.date:
    """Returns the week-start date (per WKST) on or before `d`.

    `wkst_weekday` uses Python's Monday=0..Sunday=6 convention. Anchoring
    interval arithmetic to week boundaries (rather than a raw day delta from
    DTSTART) is what makes every-N-week recurrences land on the right weeks.
    """
    return d - datetime.timedelta(days=(d.weekday() - wkst_weekday) % 7)


def event_occurs_on_date(
    *,
    starts_at: datetime.datetime,
    rrule: str | None,
    target_date: datetime.date,
    timezone: ZoneInfo = ZoneInfo("UTC"),
) -> bool:
    # Derive the start date in the CALENDAR's timezone, not UTC. `target_date` comes
    # from expand_event_windows iterating local dates, so the recurrence anchor must
    # be local too — otherwise an evening event west of UTC (whose UTC date is the
    # next day) has its whole recurrence shifted a day: the first weekly occurrence is
    # dropped, DAILY interval>=2 lands on the wrong days, and WEEKLY-without-BYDAY
    # picks the wrong weekday. Defaults to UTC (a no-op for UTC-stored events).
    start_date = starts_at.astimezone(timezone).date()
    if target_date < start_date:
        return False
    if not rrule:
        return target_date == start_date

    rule = _parse_rrule(rrule)
    until = rule.get("UNTIL")
    if until:
        until_date = _parse_until(until)
        if until_date and target_date > until_date:
            return False

    interval = int(rule.get("INTERVAL", "1"))
    freq = rule.get("FREQ", "")

    if freq == "DAILY":
        days_diff = (target_date - start_date).days
        return days_diff % interval == 0

    if freq == "WEEKLY":
        byday = rule.get("BYDAY", "")
        if byday:
            allowed = {_DAY_INDEX[d] for d in byday.split(",") if d in _DAY_INDEX}
        else:
            # RFC 5545: a WEEKLY rule with no BYDAY recurs on the DTSTART weekday.
            allowed = {start_date.weekday()}
        if target_date.weekday() not in allowed:
            return False
        if interval > 1:
            # Count whole weeks between the WKST-aligned week of DTSTART and the
            # WKST-aligned week of the target. Aligning to week boundaries (not a
            # raw day delta) ensures the OFF weeks of an every-N-week schedule
            # correctly produce no occurrences.
            wkst_weekday = _DAY_INDEX.get(rule.get("WKST", "MO"), 0)
            weeks_diff = (
                _week_start(target_date, wkst_weekday)
                - _week_start(start_date, wkst_weekday)
            ).days // 7
            if weeks_diff % interval != 0:
                return False
        return True

    return False


def event_window_on_date(
    *,
    starts_at: datetime.datetime,
    ends_at: datetime.datetime,
    target_date: datetime.date,
    timezone: ZoneInfo,
) -> tuple[datetime.datetime, datetime.datetime] | None:
    # Reapply the original local time-of-day on target_date so wall-clock
    # availability is preserved across DST transitions. Output is naive local.
    local_start = starts_at.astimezone(timezone)
    local_end = ends_at.astimezone(timezone)
    window_start = datetime.datetime(
        target_date.year, target_date.month, target_date.day,
        local_start.hour, local_start.minute, local_start.second,
    )
    window_end = datetime.datetime(
        target_date.year, target_date.month, target_date.day,
        local_end.hour, local_end.minute, local_end.second,
    )
    if window_end < window_start:
        # Overnight availability (e.g. 22:00–02:00): the end time-of-day lands on
        # the following day. Extend the window across midnight rather than drop it.
        window_end += datetime.timedelta(days=1)
    elif window_end == window_start:
        # Zero-length window — nothing bookable.
        return None
    return (window_start, window_end)


def expand_event_windows(
    events: list[Any],
    *,
    window_start: datetime.datetime,
    window_end: datetime.datetime,
    timezone: ZoneInfo,
) -> list[tuple[datetime.datetime, datetime.datetime]]:
    """Expand each event's recurrence into naive-local windows within [start, end).

    Walks every date in the query window, asks `event_occurs_on_date` whether each
    event fires, computes its wall-clock window via `event_window_on_date`, and clips
    to the query bounds. Output windows are naive datetimes in `timezone`. Shared by
    availability-slot generation and Administrative-block expansion.
    """
    window_start_local = window_start.astimezone(timezone).replace(tzinfo=None)
    window_end_local = window_end.astimezone(timezone).replace(tzinfo=None)

    local_windows: list[tuple[datetime.datetime, datetime.datetime]] = []
    current = window_start_local.date()
    last = window_end_local.date()
    while current <= last:
        for event in events:
            if not event_occurs_on_date(
                starts_at=event.starts_at,
                rrule=event.recurrence,
                target_date=current,
                timezone=timezone,
            ):
                continue
            window = event_window_on_date(
                starts_at=event.starts_at,
                ends_at=event.ends_at,
                target_date=current,
                timezone=timezone,
            )
            if window is None:
                continue
            ws, we = window
            # Clip to the overall query window.
            if we <= window_start_local or ws >= window_end_local:
                continue
            ws = max(ws, window_start_local)
            we = min(we, window_end_local)
            local_windows.append((ws, we))
        current += datetime.timedelta(days=1)
    return local_windows


def block_intervals_for_calendar(
    block_events: list[Any],
    *,
    window_start: datetime.datetime,
    window_end: datetime.datetime,
    timezone: ZoneInfo,
) -> list[tuple[datetime.datetime, datetime.datetime]]:
    """Expand Administrative-calendar block events into absolute (tz-aware) busy intervals.

    Blocks (one-off, recurring, holds, lead-time, buffers) are ordinary Events with no
    `allowed_note_types`. Expanded with the same recurrence machinery as availability,
    then localized to absolute time so they can be subtracted from any of the provider's
    slots regardless of which location calendar produced them.
    """
    return [
        (ws.replace(tzinfo=timezone), we.replace(tzinfo=timezone))
        for ws, we in expand_event_windows(
            block_events, window_start=window_start, window_end=window_end, timezone=timezone
        )
    ]


def compute_slots_for_provider(
    *,
    provider_id: str,
    provider_name: str,
    events: list[Any],
    booked: list[tuple[datetime.datetime, datetime.datetime]],
    window_start: datetime.datetime,
    window_end: datetime.datetime,
    timezone: ZoneInfo,
    duration_minutes: int,
    now: datetime.datetime,
    lead_time_minutes: int,
    location_id: str | None = None,
    location_name: str | None = None,
    location_unresolved: bool = False,
) -> list[dict]:
    now_local = now.astimezone(timezone).replace(tzinfo=None)

    local_windows = expand_event_windows(
        events, window_start=window_start, window_end=window_end, timezone=timezone
    )
    if not local_windows:
        return []

    candidate_slots = chunk_window_into_slots(local_windows, duration_minutes)
    free_slots = filter_free_slots(candidate_slots, booked)
    final_slots = apply_lead_time(free_slots, now=now_local, lead_time_minutes=lead_time_minutes)

    # Re-attach the practice timezone so the API emits tz-aware ISO strings.
    # The browser then displays slots in the patient's local time correctly,
    # regardless of where the patient is.
    return [
        {
            "provider_id": provider_id,
            "provider_name": provider_name,
            "start_iso": start.replace(tzinfo=timezone).isoformat(),
            "end_iso": end.replace(tzinfo=timezone).isoformat(),
            "location_id": location_id,
            "location_name": location_name,
            # True only when the calendar HAD a location suffix we couldn't resolve
            # (misconfig) — distinct from a benign single-site calendar with no
            # suffix. Lets BookAPI log a book-time trace for the former only.
            "location_unresolved": location_unresolved,
        }
        for start, end in final_slots
    ]


# Clinician credential abbreviations that mark a bookable provider even when the
# role isn't explicitly typed PROVIDER. Mirrors the provider lookup in Canvas's
# note_writer plugin so behavior is consistent across instances.
_PROVIDER_ROLE_ABBREVIATIONS = {"MD", "DO", "NP", "PA", "PA-C", "APRN", "CNM", "CRNA"}


def _staff_is_bookable_provider(staff: Any) -> bool:
    """True if the staff is a credentialed provider.

    Canvas models exam rooms and system/bot accounts as active Staff that can own
    scheduling calendars and even carry clinical roles (e.g. a room's "RR" role),
    so an "is this a clinician" check isn't enough. A bookable provider has a role
    typed `PROVIDER`, or one whose `public_abbreviation` is a recognized clinician
    credential (MD/DO/NP/PA/...) — the same test note_writer uses. Rooms/bots match
    neither.
    """
    for role in staff.roles.all():
        if getattr(role, "role_type", None) == "PROVIDER":
            return True
        if (getattr(role, "public_abbreviation", "") or "").strip() in _PROVIDER_ROLE_ABBREVIATIONS:
            return True
    return False


def _validate_note_type(note_type: Any) -> str | None:
    """Returns an error string if the note type is misconfigured, else None."""
    if not getattr(note_type, "is_scheduleable", False):
        return "not is_scheduleable"
    if not getattr(note_type, "is_scheduleable_via_patient_portal", False):
        return "not is_scheduleable_via_patient_portal"
    duration = getattr(note_type, "online_duration", 0) or 0
    if duration <= 0:
        return f"online_duration={duration}"
    return None


def resolve_urgent_care_note_type(note_type_name: str) -> Any:
    """Resolves the single active, portal-scheduleable NoteType named `note_type_name`.

    Returns the NoteType, or None (and logs) if it is missing, ambiguous, or
    misconfigured. Callers that both search for slots and then book share this
    so the NoteType is resolved once per request rather than twice.
    """
    from canvas_sdk.v1.data.note import NoteType
    from logger import log

    # Canvas instances often have multiple NoteTypes that share a name (legacy
    # versions, inactive copies). Pre-filter by the requirements we need so the
    # name disambiguation usually converges to one.
    candidates = list(
        NoteType.objects.filter(
            name=note_type_name,
            is_active=True,
            is_scheduleable=True,
            is_scheduleable_via_patient_portal=True,
        )
    )
    if not candidates:
        log.error(
            f"slot_search: no active scheduleable NoteType named {note_type_name!r}"
        )
        return None
    if len(candidates) > 1:
        log.error(
            f"slot_search: multiple active scheduleable NoteTypes named {note_type_name!r}; "
            "rename one to disambiguate"
        )
        return None

    note_type = candidates[0]
    misconfig = _validate_note_type(note_type)
    if misconfig:
        log.error(f"slot_search: NoteType {note_type_name!r} misconfigured ({misconfig})")
        return None
    return note_type


def _slot_instant(slot: dict) -> datetime.datetime:
    """Absolute (UTC) instant a slot starts at, for tz-agnostic dedup and sorting.

    A slot's `start_iso` carries its calendar's UTC offset, so slots from
    different-timezone calendars must be compared by instant, not by string.
    """
    return datetime.datetime.fromisoformat(slot["start_iso"]).astimezone(datetime.timezone.utc)


def _calendar_timezone(calendar: Any, default: ZoneInfo) -> ZoneInfo:
    """The calendar's own timezone, normalized to a `ZoneInfo`.

    `Calendar.timezone` is the authoritative per-calendar zone — we never infer it
    from the title/location suffix. It is normally always populated, but we defend
    against a missing/blank/unparseable value by falling back to `default` and
    logging it (a blank/bad value is a data problem that would otherwise shift every
    slot silently by the offset delta). The field may surface as a `ZoneInfo` or
    another tzinfo; coerce by IANA key so the sandbox-allowlisted `ZoneInfo` flows
    downstream.
    """
    from logger import log

    title = getattr(calendar, "title", "?")
    raw = getattr(calendar, "timezone", None)
    if raw is None:
        log.warning(
            f"_calendar_timezone: calendar {title!r} has no timezone; "
            f"falling back to {default.key} — its availability may be off"
        )
        return default
    try:
        return ZoneInfo(str(raw))
    except (KeyError, ValueError):
        log.warning(
            f"_calendar_timezone: calendar {title!r} has unparseable timezone {raw!r}; "
            f"falling back to {default.key} — its availability may be off"
        )
        return default


def find_available_slots(
    *,
    note_type_name: str,
    window_start: datetime.datetime,
    window_end: datetime.datetime,
    practice_timezone: ZoneInfo,
    now: datetime.datetime,
    lead_time_minutes: int = 30,
    max_results: int = 50,
    note_type: Any = None,
    location_index: dict[str, tuple[str, str]] | None = None,
) -> list[dict]:
    """Returns slots [{provider_id, provider_name, start_iso, end_iso, location_id, location_name}], sorted by instant.

    Each clinic calendar's availability is interpreted in its OWN `Calendar.timezone`
    (a required field — not guessed from the title), with `practice_timezone` as a
    fallback only if that value fails to resolve. A provider with calendars at more
    than one location is bookable across the union of all of them, deduped by
    absolute instant — so a telehealth provider available at two locations at the
    same moment yields one slot, not two. `max_results` caps slots **per provider**
    (not globally), so no provider is crowded out of the results.

    Returns [] (and logs) if the configured NoteType is missing, ambiguous, or
    misconfigured. Pass a pre-resolved `note_type` (from
    `resolve_urgent_care_note_type`) to avoid resolving it a second time.
    """
    from canvas_sdk.v1.data.appointment import Appointment
    from canvas_sdk.v1.data.calendar import Calendar, Event
    from canvas_sdk.v1.data.staff import Staff
    from logger import log

    location_index = location_index or {}
    log.info(
        f"slot_search: searching note_type={note_type_name!r} "
        f"window={window_start.isoformat()}..{window_end.isoformat()} "
        f"fallback_tz={practice_timezone.key} lead={lead_time_minutes}min"
    )

    if note_type is None:
        note_type = resolve_urgent_care_note_type(note_type_name)
    if note_type is None:
        return []

    duration_minutes = note_type.online_duration
    log.info(
        f"slot_search: NoteType resolved id={getattr(note_type, 'id', '?')} "
        f"online_duration={duration_minutes}min"
    )

    clinic_calendars = list(Calendar.objects.filter(title__icontains=": Clinic"))
    if not clinic_calendars:
        log.error(
            "slot_search: no Calendars with ': Clinic' in title — "
            "create one per provider titled '{Provider full_name}: Clinic'"
        )
        return []
    log.info(
        f"slot_search: found {len(clinic_calendars)} clinic-titled calendars: "
        f"{[c.title for c in clinic_calendars[:10]]}"
    )

    # `Staff.full_name` is a Python property (not a queryable field), so we fetch
    # active staff once and look up by name in memory. Typical clinics have <100
    # active providers — acceptable. Build a lookup map.
    #
    # Calendars carry no FK to Staff (the SDK matches them by the title string
    # "{full_name}: Clinic"), so a name is the only join key we have. If two
    # active staff share a full_name we cannot tell their calendars apart, so we
    # drop the ambiguous name entirely rather than risk booking the wrong
    # provider's record.
    staff_by_name: dict[str, Any] = {}
    ambiguous_names: set[str] = set()
    excluded_non_providers: list[str] = []
    # `prefetch_related("roles")` so the per-staff Provider-role check below reads
    # from cache rather than firing a query per staff member.
    active_staff = list(Staff.objects.filter(active=True).prefetch_related("roles"))
    for staff in active_staff:
        # Exam rooms ("RR" role) and system/bot accounts are active Staff that can
        # own scheduling calendars but carry no Provider-type role. A patient must
        # never be offered one as a bookable provider.
        if not _staff_is_bookable_provider(staff):
            excluded_non_providers.append(staff.full_name)
            continue
        if staff.full_name in staff_by_name:
            ambiguous_names.add(staff.full_name)
        staff_by_name[staff.full_name] = staff
    for name in ambiguous_names:
        staff_by_name.pop(name, None)
        log.error(
            f"slot_search: multiple active Staff share full_name {name!r}; "
            "skipping that provider's calendars until the names are disambiguated"
        )
    if excluded_non_providers:
        log.info(
            f"slot_search: excluded {len(excluded_non_providers)} active staff with no "
            f"Provider role (rooms/resources/bots): {excluded_non_providers}"
        )
    log.info(
        f"slot_search: {len(staff_by_name)} uniquely-named provider staff. "
        f"full_names={list(staff_by_name.keys())[:20]}"
    )

    # First pass: resolve calendar↔staff pairings in memory (no DB).
    pairings: list[tuple[Any, Any]] = []
    for calendar in clinic_calendars:
        provider_name, calendar_type, _ = parse_calendar_title(calendar.title)
        if calendar_type.lower() != "clinic":
            log.warning(
                f"slot_search: calendar {calendar.title!r} parsed type "
                f"{calendar_type!r} != 'Clinic' (need exact 'Clinic' after first colon), skipping"
            )
            continue
        staff = staff_by_name.get(provider_name)
        if staff is None:
            log.warning(
                f"slot_search: calendar {calendar.title!r} provider name "
                f"{provider_name!r} did not match any active Staff.full_name "
                "(must equal '{first_name} {last_name}' exactly), skipping"
            )
            continue
        pairings.append((calendar, staff))
    if not pairings:
        log.error(
            "slot_search: no calendar↔staff pairings — "
            "check calendar title format and Staff.full_name exact-match"
        )
        return []
    log.info(f"slot_search: matched {len(pairings)} calendar↔staff pairings")

    # Calendar.dbid is the integer PK that Event.calendar (FK) actually
    # references — Calendar.id is a UUID and is NOT what Event.calendar_id holds.
    unique_calendar_dbids = {c.dbid for c, _ in pairings}
    unique_staff_dbids = {s.dbid for _, s in pairings}

    # Bulk-fetch events for all relevant calendars in a single query.
    events_by_calendar_dbid: dict[Any, list[Any]] = {}
    for ev in Event.objects.filter(
        calendar_id__in=unique_calendar_dbids,
        is_cancelled=False,
        allowed_note_types=note_type,
    ).distinct():
        events_by_calendar_dbid.setdefault(ev.calendar_id, []).append(ev)
    log.info(
        "slot_search: events per calendar (filter: is_cancelled=False AND "
        f"allowed_note_types={note_type_name!r}): "
        f"{ {c.title: len(events_by_calendar_dbid.get(c.dbid, [])) for c, _ in pairings} }"
    )

    # Bulk-fetch booked appointments for all relevant providers in a single query.
    # Stored as absolute (tz-aware) intervals — each provider calendar converts them
    # into its own location timezone when filtering, so the comparison stays correct
    # regardless of which location's calendar a slot came from.
    booked_by_provider_dbid: dict[int, list[tuple[datetime.datetime, datetime.datetime]]] = {}
    appt_count = 0
    for appt in (
        Appointment.objects.filter(
            provider_id__in=unique_staff_dbids,
            start_time__gte=window_start - _APPOINTMENT_QUERY_BUFFER,
            start_time__lt=window_end + _APPOINTMENT_QUERY_BUFFER,
        )
        .exclude(status__in=_NON_BLOCKING_APPOINTMENT_STATUSES)
        .only("provider_id", "start_time", "duration_minutes")
    ):
        if not (appt.start_time and appt.duration_minutes):
            continue
        end_abs = appt.start_time + datetime.timedelta(minutes=appt.duration_minutes)
        booked_by_provider_dbid.setdefault(appt.provider_id, []).append(
            (appt.start_time, end_abs)
        )
        appt_count += 1
    log.info(f"slot_search: {appt_count} blocking appointments in window")

    # Honor Administrative-calendar blocks. provider_availability writes one-off
    # blocks, recurring blocks, holds, lead-time blocks, and appointment buffers to
    # "{Provider}: Administrative[: {Location}]" calendars (events with no
    # allowed_note_types). Expand them into absolute busy intervals — in each
    # calendar's own timezone — and merge into the provider's booked set so they're
    # subtracted from availability exactly like appointments. A block removes that
    # absolute instant from ALL of the provider's slots (telehealth-safe: a provider
    # blocked at an instant isn't bookable at any location).
    admin_pairings: list[tuple[Any, Any]] = []
    for calendar in Calendar.objects.filter(title__icontains=": Admin"):
        provider_name, calendar_type, _ = parse_calendar_title(calendar.title)
        if not calendar_type.lower().startswith("admin"):
            continue
        staff = staff_by_name.get(provider_name)
        if staff is not None:
            admin_pairings.append((calendar, staff))
        else:
            log.warning(
                f"slot_search: Administrative calendar {calendar.title!r} provider name "
                f"{provider_name!r} did not match any active Staff.full_name — that "
                "provider's blocks will NOT be subtracted (they may be over-booked)"
            )

    block_count = 0
    if admin_pairings:
        admin_events_by_calendar_dbid: dict[Any, list[Any]] = {}
        for ev in Event.objects.filter(
            calendar_id__in={c.dbid for c, _ in admin_pairings},
            is_cancelled=False,
        ):
            admin_events_by_calendar_dbid.setdefault(ev.calendar_id, []).append(ev)
        for calendar, staff in admin_pairings:
            block_events = admin_events_by_calendar_dbid.get(calendar.dbid, [])
            if not block_events:
                continue
            tz = _calendar_timezone(calendar, practice_timezone)
            intervals = block_intervals_for_calendar(
                block_events, window_start=window_start, window_end=window_end, timezone=tz
            )
            booked_by_provider_dbid.setdefault(staff.dbid, []).extend(intervals)
            block_count += len(intervals)
    log.info(f"slot_search: {block_count} administrative block intervals in window")

    # Group every clinic calendar a provider owns — possibly several, across
    # locations — so the provider's availability is the union of all of them.
    calendars_by_provider: dict[str, tuple[Any, list[Any]]] = {}
    for calendar, staff in pairings:
        _, calendars = calendars_by_provider.setdefault(str(staff.id), (staff, []))
        calendars.append(calendar)

    all_slots: list[dict] = []
    for provider_id, (staff, calendars) in calendars_by_provider.items():
        booked_abs = booked_by_provider_dbid.get(staff.dbid, [])
        provider_slots: list[dict] = []
        for calendar in calendars:
            events = events_by_calendar_dbid.get(calendar.dbid, [])
            if not events:
                log.warning(
                    f"slot_search: calendar {calendar.title!r} has 0 events with "
                    f"allowed_note_types={note_type_name!r} and is_cancelled=False — "
                    "did you add the urgent-care NoteType to the event's allowed_note_types?"
                )
                continue
            # Interpret this calendar's availability in its OWN timezone — the
            # required Calendar.timezone field, never inferred from the title.
            tz = _calendar_timezone(calendar, practice_timezone)
            # Resolve the calendar's location from its title suffix
            # ("{Provider}: Clinic: {Location full_name}") so each slot carries the
            # location it would book into.
            _, _, location_suffix = parse_calendar_title(calendar.title)
            location_unresolved = False
            if not location_suffix:
                # No location in the title (single-site calendar) — booking falls
                # back to the active location, no label shown. Benign, not flagged.
                location_id, location_name = None, None
            elif location_suffix in location_index:
                location_id, location_name = location_index[location_suffix]
            else:
                # Suffix present but unresolved — either it matches no active
                # PracticeLocation.full_name (rename / casing / whitespace mismatch)
                # or that name was dropped by _location_index as an ambiguous
                # duplicate. Drop the label (never show a location we can't book
                # into), log it, and flag the slot so BookAPI logs a book-time trace
                # when one is actually booked — distinct from the benign no-suffix case.
                log.error(
                    f"slot_search: calendar {calendar.title!r} location suffix "
                    f"{location_suffix!r} did not resolve to an active PracticeLocation "
                    "(unknown or ambiguous-duplicate name); slot will show no location "
                    "and book the default location"
                )
                location_id, location_name = None, None
                location_unresolved = True
            log.info(
                f"slot_search: calendar {calendar.title!r} tz={tz.key} "
                f"location={location_name!r} ({len(events)} events)"
            )
            booked_tz = [
                (
                    b_start.astimezone(tz).replace(tzinfo=None),
                    b_end.astimezone(tz).replace(tzinfo=None),
                )
                for b_start, b_end in booked_abs
            ]
            provider_slots.extend(
                compute_slots_for_provider(
                    provider_id=provider_id,
                    provider_name=staff.full_name,
                    events=events,
                    booked=booked_tz,
                    window_start=window_start,
                    window_end=window_end,
                    timezone=tz,
                    duration_minutes=duration_minutes,
                    now=now,
                    lead_time_minutes=lead_time_minutes,
                    location_id=location_id,
                    location_name=location_name,
                    location_unresolved=location_unresolved,
                )
            )

        # Union across the provider's calendars: one slot per absolute instant,
        # ordered, then capped PER PROVIDER. Capping per provider (rather than a
        # single global cap applied after merging) ensures a provider whose
        # availability falls later in the window is still represented instead of
        # being crowded out by earlier providers.
        deduped: list[dict] = []
        seen_instants: set[datetime.datetime] = set()
        for slot in sorted(provider_slots, key=_slot_instant):
            instant = _slot_instant(slot)
            if instant in seen_instants:
                continue
            seen_instants.add(instant)
            deduped.append(slot)
        capped = deduped[:max_results]
        log.info(
            f"slot_search: provider {staff.full_name!r} across {len(calendars)} calendar(s) "
            f"→ {len(deduped)} bookable slots (per-provider cap {max_results} → {len(capped)})"
        )
        all_slots.extend(capped)

    # Sort the union by absolute instant (NOT by start_iso string — slots from
    # different-tz locations carry different UTC offsets, so string order isn't
    # chronological). The result is already bounded by the per-provider cap above.
    all_slots.sort(key=_slot_instant)
    log.info(f"slot_search: returning {len(all_slots)} total slots")
    return all_slots
