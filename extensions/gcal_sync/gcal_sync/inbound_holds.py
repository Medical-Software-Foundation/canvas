"""Build Canvas admin-hold effects from inbound Google events (Google → Canvas).

A brand-new event on a provider's Google calendar (no Canvas marker) becomes a Canvas **schedule
event** (admin hold) blocking that provider's availability. This is safe to write back — it carries
no patient and doesn't touch appointment scheduling rules — unlike Google→Canvas *appointment*
mutations, which remain gated off.

The created hold is stamped with the Google event id via ``external_identifiers`` so the outbound
push skips it (loop suppression, see :func:`gcal_sync.appointment_snapshot.google_origin_event_id`).
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
    event: dict, note_type_id: str | None, provider_id: str | None, location_id: str | None
) -> Effect | None:
    """Build a ``ScheduleEvent.create()`` effect for a new Google event, or ``None`` if we can't.

    The note type and provider/location are resolved ONCE per calendar by the caller (they are
    identical for every event in a pull) and passed in — not re-queried per event. Returns ``None``
    when that context is incomplete (no note type / provider / location) or the event time is
    unparseable, so the caller can skip rather than crash.
    """
    if not note_type_id or not provider_id or not location_id:
        return None

    window = parse_event_window(event)
    if window is None:
        return None
    start_time, duration_minutes = window

    # Private events: block the time but never copy the real name into Canvas.
    if is_private(event):
        title = PRIVATE_EVENT_LABEL
    else:
        title = (event.get("summary") or "Busy")[:_MAX_TITLE_LEN]

    schedule_event = ScheduleEvent(
        note_type_id=note_type_id,
        provider_id=provider_id,
        practice_location_id=location_id,
        start_time=start_time,
        duration_minutes=duration_minutes,
        description=title,
        external_identifiers=[AppointmentIdentifier(system=GOOGLE_ORIGIN_SYSTEM, value=event["id"])],
    )
    return schedule_event.create()
