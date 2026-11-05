"""Build Canvas admin-hold effects from inbound Google events (Google → Canvas).

A brand-new event on a provider's Google calendar (no Canvas marker) becomes a Canvas **schedule
event** (admin hold) blocking that provider's availability. This is safe to write back — it carries
no patient and doesn't touch appointment scheduling rules — unlike Google→Canvas *appointment*
mutations, which remain gated off.

The created hold is stamped with the Google event id via ``external_identifiers`` so the outbound
push skips it (loop suppression, see :func:`gcal_sync.appointment_snapshot.google_origin_event_id`).

**Multi-day events expand to one hold per day.** Canvas blocks a hold's *date of service* only, so a
single hold carrying a multi-day duration leaves every day after the first bookable. An event that
covers more than one date in the provider's time zone (or any all-day event) is therefore expanded
into one hold per covered day (see :func:`event_day_spans`), each carrying its own
``{google_event_id}:{YYYY-MM-DD}`` identifier so the dedup / update / delete lookups in
:mod:`gcal_sync.inbound` work per day.

This covers timed spans as well as all-day events: Google stores an out-of-office block as a timed
``dateTime`` span from local midnight to local midnight, not as a ``date`` event.
"""

import datetime
from typing import NamedTuple
from zoneinfo import ZoneInfo

import arrow

from canvas_sdk.effects import Effect
from canvas_sdk.effects.note import AppointmentIdentifier
from canvas_sdk.effects.note.appointment import ScheduleEvent
from canvas_sdk.v1.data.note import NoteType
from canvas_sdk.v1.data.staff import Staff
from logger import log

from gcal_sync.appointment_snapshot import GOOGLE_ORIGIN_SYSTEM
from gcal_sync.google.client import CALENDAR_TIME_ZONE_KEY
from gcal_sync.models import StaffCalendarMapping

# Google caps event titles to non-PHI provider text; we still bound what we copy into Canvas.
_MAX_TITLE_LEN = 255

# Canvas's "Generic event" schedule-event note type — the default home for imported Google holds.
DEFAULT_SCHEDULE_EVENT_CODE = "272379006"

# Private events are imported (if enabled) with their name hidden — we block the time but never copy
# the real title (e.g. "Dad - Dr. Appt") into Canvas.
PRIVATE_EVENT_LABEL = "Busy"
_PRIVATE_VISIBILITIES = {"private", "confidential"}

# One multi-day event can legitimately run long (a sabbatical, a seasonal closure) and each covered day
# becomes its own Canvas hold, so cap the expansion rather than minting an unbounded number of
# appointments from one Google event. Sized to just past the inbound import window (+6 months), so
# the window stays the binding constraint and the cap is only a sanity bound — real events do run
# long (one live install carries a 238-day hold), and anything past the cap is left unblocked, which
# is the failure this fix exists to prevent.
MAX_SPAN_DAYS = 186

# The zone a day is cut in when neither the event nor its calendar names one (the clinic's zone).
DEFAULT_TIME_ZONE = "America/New_York"


class DaySpan(NamedTuple):
    """The part of an event that falls on one local date: what one per-day hold blocks."""

    date: str  # YYYY-MM-DD in the event's time zone; also the hold's identifier suffix
    start: datetime.datetime  # UTC
    duration_minutes: int


def ingest_private_events(secrets: dict) -> bool:
    """Org toggle: import private/confidential events? Default True. Names are always masked."""
    return (secrets.get("INGEST_PRIVATE_EVENTS") or "true").strip().lower() != "false"


def ingest_all_day_events(secrets: dict) -> bool:
    """Org toggle: import all-day events (Home / birthdays / OOO)? Default False."""
    return (secrets.get("INGEST_ALL_DAY_EVENTS") or "false").strip().lower() == "true"


def is_private(event: dict) -> bool:
    return (event.get("visibility") or "").lower() in _PRIVATE_VISIBILITIES


def is_all_day(event: dict) -> bool:
    # All-day Google events carry ``start.date`` (a date) instead of ``start.dateTime``.
    start = event.get("start") or {}
    return bool(start.get("date")) and not start.get("dateTime")


def event_time_zone(event: dict) -> ZoneInfo:
    """The zone the provider's days are cut in for this event.

    The event's own ``start.timeZone`` first (Google sets it on timed events, including out-of-office
    blocks), then the calendar's zone carried on the event (all-day events never name one), then
    :data:`DEFAULT_TIME_ZONE`. An unknown zone name falls through to the next candidate.
    """
    candidates = (
        (event.get("start") or {}).get("timeZone"),
        event.get(CALENDAR_TIME_ZONE_KEY),
        DEFAULT_TIME_ZONE,
    )
    for name in candidates:
        if not name:
            continue
        try:
            return ZoneInfo(str(name))
        except (KeyError, ValueError):
            # ZoneInfoNotFoundError subclasses KeyError; a malformed key raises ValueError.
            log.info("gcal inbound: unknown time zone %r on event %s", name, event.get("id"))
    return ZoneInfo(DEFAULT_TIME_ZONE)


# The plugin sandbox allows only arrow.get/now/utcnow, and Python 3.13 evaluates annotations at load.
def _local_time(day: datetime.date, hour: int, minute: int, zone: ZoneInfo) -> "arrow.Arrow":
    return arrow.get(datetime.datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone))


def event_day_spans(event: dict) -> list[DaySpan]:
    """Split an event into the part that falls on each local date it covers.

    Days are cut in :func:`event_time_zone`. A fully covered day blocks 00:00 to 23:59 local, so the
    hold stays inside its own date: a block that runs into the next date leaves the day bookable on
    the Canvas schedule. A partially covered first or last day keeps the event's real start or end.

    Google stores an all-day event's ``end.date`` **exclusively**, so PTO entered for 8/31 through
    9/4 arrives as ``start.date=2026-08-31`` / ``end.date=2026-09-05`` and covers five days. A timed
    out-of-office block arrives the same way as ``dateTime`` values at local midnight. A missing or
    non-advancing end means a single day (all-day) or 30 minutes (timed), matching
    :func:`parse_event_window`.

    Returns ``[]`` for an unparseable event. Capped at :data:`MAX_SPAN_DAYS` days.
    """
    zone = event_time_zone(event)
    start_field = event.get("start") or {}
    end_field = event.get("end") or {}
    try:
        if is_all_day(event):
            first = arrow.get(str(start_field["date"]), "YYYY-MM-DD").date()
            end_date = (
                arrow.get(str(end_field["date"]), "YYYY-MM-DD").date()
                if end_field.get("date")
                else first
            )
            if end_date <= first:
                end_date = first + datetime.timedelta(days=1)
            start_local = _local_time(first, 0, 0, zone)
            end_local = _local_time(end_date, 0, 0, zone)
        else:
            start_raw = start_field.get("dateTime")
            if not start_raw:
                return []
            start_local = arrow.get(start_raw).to(zone)
            end_raw = end_field.get("dateTime")
            end_local = arrow.get(end_raw).to(zone) if end_raw else start_local.shift(minutes=30)
            if end_local <= start_local:
                end_local = start_local.shift(minutes=30)
    except (KeyError, TypeError, ValueError):
        # arrow's ParserError subclasses ValueError; referencing it by attribute would be one more
        # name for the plugin sandbox to resolve for no benefit.
        return []

    spans: list[DaySpan] = []
    day = start_local.date()
    while _local_time(day, 0, 0, zone) < end_local:
        if len(spans) >= MAX_SPAN_DAYS:
            log.info(
                "gcal inbound: event %s spans more than %s days; blocking the first %s only",
                event.get("id"),
                MAX_SPAN_DAYS,
                MAX_SPAN_DAYS,
            )
            break
        next_midnight = _local_time(day + datetime.timedelta(days=1), 0, 0, zone)
        seg_start = max(start_local, _local_time(day, 0, 0, zone))
        # Running to (or past) midnight means the rest of the day: stop at 23:59 so the hold never
        # crosses into the next date.
        seg_end = (
            end_local if end_local < next_midnight else _local_time(day, 23, 59, zone)
        )
        # Elapsed time, measured in UTC: subtracting two times that share a zone gives the wall-clock
        # difference, which is an hour off on a DST-change day.
        minutes = int((seg_end.to("UTC") - seg_start.to("UTC")).total_seconds() // 60)
        if minutes > 0:
            spans.append(
                DaySpan(day.isoformat(), seg_start.to("UTC").datetime, minutes)
            )
        day += datetime.timedelta(days=1)
    return spans


def hold_external_id(google_event_id: str, date: str | None = None) -> str:
    """External-identifier value for a hold: the bare event id, or ``{event_id}:{YYYY-MM-DD}``.

    A multi-day event expands into one hold per covered day, and each needs its own stable identifier
    so the dedup / update / delete lookups resolve per day. Google event ids are base32hex-style and
    never contain ``:``, so ``{event_id}:`` matches that event's per-day holds and nothing else.
    """
    return f"{google_event_id}:{date}" if date else google_event_id


def hold_title(event: dict) -> str:
    """The description to write into Canvas: the event summary, or ``Busy`` when private.

    Private/confidential events are blocked but never named — the real title (e.g. "Dad - Dr. Appt")
    is not copied into Canvas on create or on update.
    """
    if is_private(event):
        return PRIVATE_EVENT_LABEL
    return (event.get("summary") or "Busy")[:_MAX_TITLE_LEN]


def schedule_event_note_type_id(secrets: dict) -> str | None:
    """Resolve the NoteType to use for created holds.

    Uses the code in ``SCHEDULE_EVENT_NOTE_TYPE_CODE`` if set, else the "Generic event" code
    (``272379006``). Falls back to any schedule-event note type if that code isn't present, so a
    misconfigured/absent code never wholly blocks inbound holds. Returns ``None`` only if the
    instance has no schedule-event note type at all.
    """
    code = (secrets.get("SCHEDULE_EVENT_NOTE_TYPE_CODE") or "").strip() or DEFAULT_SCHEDULE_EVENT_CODE
    note_type_id = (
        NoteType.objects.filter(category="schedule_event", code=code)
        .values_list("id", flat=True)
        .first()
    )
    if not note_type_id:
        # Fallback: any schedule-event note type (alphabetical) so imports still succeed.
        note_type_id = (
            NoteType.objects.filter(category="schedule_event")
            .values_list("id", flat=True)
            .order_by("name")
            .first()
        )
    return str(note_type_id) if note_type_id else None


def provider_and_location(calendar_id: str) -> tuple[str, str] | None:
    """Return ``(provider_id, practice_location_id)`` for an enrolled calendar, or ``None``.

    Uses the staff↔calendar mapping to find the provider, then their primary practice location
    (required by the ScheduleEvent effect).
    """
    staff_id = (
        StaffCalendarMapping.objects.filter(google_calendar_id=calendar_id, active=True)
        .values_list("canvas_staff_id", flat=True)
        .first()
    )
    if not staff_id:
        return None
    location_id = (
        Staff.objects.filter(id=staff_id)
        .values_list("primary_practice_location__id", flat=True)
        .first()
    )
    if not location_id:
        log.info("Provider %s has no primary practice location; cannot create hold", staff_id)
        return None
    return str(staff_id), str(location_id)


def parse_event_window(event: dict) -> tuple[datetime.datetime, int] | None:
    """Return ``(start_datetime, duration_minutes)`` for a Google event, or ``None`` if unparseable.

    Handles both timed events (``start.dateTime``) and all-day events (``start.date``).
    """
    start_raw = (event.get("start") or {}).get("dateTime") or (event.get("start") or {}).get("date")
    end_raw = (event.get("end") or {}).get("dateTime") or (event.get("end") or {}).get("date")
    if not start_raw:
        return None
    start = arrow.get(start_raw)
    end = arrow.get(end_raw) if end_raw else start.shift(minutes=30)
    duration = int((end - start).total_seconds() // 60)
    if duration <= 0:
        duration = 30
    return start.to("UTC").datetime, duration


def build_hold_effect(
    event: dict,
    note_type_id: str | None,
    provider_id: str | None,
    location_id: str | None,
    day: DaySpan | None = None,
) -> Effect | None:
    """Build a ``ScheduleEvent.create()`` effect for a new Google event, or ``None`` if we can't.

    The note type and provider/location are resolved ONCE per calendar by the caller (they are
    identical for every event in a pull) and passed in — not re-queried per event. Returns ``None``
    when that context is incomplete (no note type / provider / location) or the event time is
    unparseable, so the caller can skip rather than crash.

    Pass ``day`` (from :func:`event_day_spans`) to build one day of an expanded multi-day event: the
    hold covers that day's span and is identified as ``{event_id}:{date}``. Without it the hold takes
    the event's own window and the bare event id.
    """
    if not note_type_id or not provider_id or not location_id:
        return None

    if day is not None:
        start_time = day.start
        duration_minutes = day.duration_minutes
    else:
        window = parse_event_window(event)
        if window is None:
            return None
        start_time, duration_minutes = window

    schedule_event = ScheduleEvent(
        note_type_id=note_type_id,
        provider_id=provider_id,
        practice_location_id=location_id,
        start_time=start_time,
        duration_minutes=duration_minutes,
        description=hold_title(event),
        external_identifiers=[
            AppointmentIdentifier(
                system=GOOGLE_ORIGIN_SYSTEM,
                value=hold_external_id(event["id"], day.date if day is not None else None),
            )
        ],
    )
    return schedule_event.create()
