"""Build Canvas admin-hold effects from inbound Google events (Google → Canvas).

A brand-new event on a provider's Google calendar (no Canvas marker) becomes a Canvas **schedule
event** (admin hold) blocking that provider's availability. This is safe to write back — it carries
no patient and doesn't touch appointment scheduling rules — unlike Google→Canvas *appointment*
mutations, which remain gated off.

The created hold is stamped with the Google event id via ``external_identifiers`` so the outbound
push skips it (loop suppression, see :func:`gcal_sync.appointment_snapshot.google_origin_event_id`).

**All-day events expand to one hold per day.** Canvas blocks a hold's *date of service* only, so a
single hold carrying a multi-day duration leaves every day after the first bookable. An all-day
Google event is therefore expanded into one hold per covered day (see :func:`all_day_dates`), each
carrying its own ``{google_event_id}:{YYYY-MM-DD}`` identifier so the dedup / update / delete lookups
in :mod:`gcal_sync.inbound` work per day.
"""

from datetime import datetime

import arrow

from canvas_sdk.effects import Effect
from canvas_sdk.effects.note import AppointmentIdentifier
from canvas_sdk.effects.note.appointment import ScheduleEvent
from canvas_sdk.v1.data.note import NoteType
from canvas_sdk.v1.data.staff import Staff
from logger import log

from gcal_sync.appointment_snapshot import GOOGLE_ORIGIN_SYSTEM
from gcal_sync.models import StaffCalendarMapping

# Google caps event titles to non-PHI provider text; we still bound what we copy into Canvas.
_MAX_TITLE_LEN = 255

# Canvas's "Generic event" schedule-event note type — the default home for imported Google holds.
DEFAULT_SCHEDULE_EVENT_CODE = "272379006"

# Private events are imported (if enabled) with their name hidden — we block the time but never copy
# the real title (e.g. "Dad - Dr. Appt") into Canvas.
PRIVATE_EVENT_LABEL = "Busy"
_PRIVATE_VISIBILITIES = {"private", "confidential"}

# An expanded all-day hold blocks its whole date.
ALL_DAY_DURATION_MINUTES = 1440

# One all-day event can legitimately run long (a sabbatical, a seasonal closure) and each covered day
# becomes its own Canvas hold, so cap the expansion rather than minting an unbounded number of
# appointments from one Google event. Sized to just past the inbound import window (+6 months), so
# the window stays the binding constraint and the cap is only a sanity bound — real events do run
# long (one live install carries a 134-day all-day hold), and anything past the cap is left
# unblocked, which is the failure this fix exists to prevent.
MAX_ALL_DAY_SPAN_DAYS = 186


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


def all_day_dates(event: dict) -> list[str]:
    """The dates an all-day event covers, as ``YYYY-MM-DD`` strings.

    Google stores an all-day event's ``end.date`` **exclusively**, so PTO entered for 8/31 through
    9/4 arrives as ``start.date=2026-08-31`` / ``end.date=2026-09-05`` and covers five days. A
    missing or non-advancing ``end.date`` means a single day. Returns ``[]`` for a timed event or an
    unparseable date, so the caller falls back to the ordinary single-hold path.

    Capped at :data:`MAX_ALL_DAY_SPAN_DAYS` days.
    """
    if not is_all_day(event):
        return []
    start_raw = str((event.get("start") or {}).get("date") or "")
    end_raw = str((event.get("end") or {}).get("date") or "")
    if not start_raw:
        return []
    try:
        start = arrow.get(start_raw, "YYYY-MM-DD")
        end = arrow.get(end_raw, "YYYY-MM-DD") if end_raw else start.shift(days=1)
    except (TypeError, ValueError):
        # arrow's ParserError subclasses ValueError; referencing it by attribute would be one more
        # name for the plugin sandbox to resolve for no benefit.
        return []
    if end <= start:
        end = start.shift(days=1)
    span = (end - start).days
    if span > MAX_ALL_DAY_SPAN_DAYS:
        log.info(
            "gcal inbound: all-day event %s spans %s days; blocking the first %s only",
            event.get("id"),
            span,
            MAX_ALL_DAY_SPAN_DAYS,
        )
        span = MAX_ALL_DAY_SPAN_DAYS
    return [start.shift(days=offset).format("YYYY-MM-DD") for offset in range(span)]


def hold_external_id(google_event_id: str, date: str | None = None) -> str:
    """External-identifier value for a hold: the bare event id, or ``{event_id}:{YYYY-MM-DD}``.

    An all-day event expands into one hold per covered day, and each needs its own stable identifier
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


def parse_event_window(event: dict) -> tuple[datetime, int] | None:
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
    date: str | None = None,
) -> Effect | None:
    """Build a ``ScheduleEvent.create()`` effect for a new Google event, or ``None`` if we can't.

    The note type and provider/location are resolved ONCE per calendar by the caller (they are
    identical for every event in a pull) and passed in — not re-queried per event. Returns ``None``
    when that context is incomplete (no note type / provider / location) or the event time is
    unparseable, so the caller can skip rather than crash.

    Pass ``date`` (``YYYY-MM-DD``) to build one day of an expanded all-day event: the hold covers
    that whole date and is identified as ``{event_id}:{date}``. Without it the hold takes the event's
    own window and the bare event id.
    """
    if not note_type_id or not provider_id or not location_id:
        return None

    if date:
        start_time = arrow.get(date, "YYYY-MM-DD").to("UTC").datetime
        duration_minutes = ALL_DAY_DURATION_MINUTES
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
                system=GOOGLE_ORIGIN_SYSTEM, value=hold_external_id(event["id"], date)
            )
        ],
    )
    return schedule_event.create()
