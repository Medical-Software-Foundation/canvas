import datetime
import json
from http import HTTPStatus
from zoneinfo import ZoneInfo

import arrow

from canvas_sdk.effects import Effect
from canvas_sdk.effects.calendar import (
    DaysOfWeek,
    Event,
    EventRecurrence,
)
from canvas_sdk.effects.simple_api import Response
from canvas_sdk.handlers.simple_api import SimpleAPIRoute, StaffSessionAuthMixin
from canvas_sdk.v1.data import Calendar, PracticeLocation
from canvas_sdk.v1.data.calendar import Event as EventModel
from canvas_sdk.v1.data.staff import Staff

from scheduling_with_rooms.utils.staff_lookup import parse_schedulable_roles


def _calendar_tz(calendar_id: str) -> ZoneInfo:
    """Resolve a calendar's timezone, falling back to UTC."""
    if not calendar_id:
        return ZoneInfo("UTC")
    cal = Calendar.objects.filter(id=calendar_id).first()
    tz_name = str(cal.timezone) if cal and cal.timezone else "UTC"
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("UTC")


def _calendar_tz_for_event(event_id: str) -> ZoneInfo:
    if not event_id:
        return ZoneInfo("UTC")
    ev = EventModel.objects.filter(id=event_id).select_related("calendar").first()
    if not ev or not ev.calendar:
        return ZoneInfo("UTC")
    return _calendar_tz(str(ev.calendar.id))


def _parse_dt(value: str | None, cal_tz: ZoneInfo) -> datetime.datetime | None:
    """Parse a datetime string. Naive values are assumed to be in cal_tz."""
    if not value:
        return None
    s = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(s)
    except ValueError:
        # Fall back to arrow which is more lenient.
        dt = arrow.get(s).datetime
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=cal_tz)
    return dt


def _serialize_event(event, providers, locations, view_tz=None):
    """Match the shape rendered by AvailabilityWebApp.index()'s `events` context.

    Times are emitted in ``view_tz`` (when provided) or the calendar's own
    timezone otherwise. The client passes a `tz` query param so the user can
    pick which wall-clock they edit in; storage stays in UTC.
    """
    cal_title = event.calendar.title if event.calendar else ""
    cal_description = (event.calendar.description or "") if event.calendar else ""
    cal_type = ""
    prov_name = ""
    title_loc_name = ""
    if cal_title:
        parts = [p.strip() for p in cal_title.split(":")]
        if parts:
            prov_name = parts[0]
        if len(parts) >= 2:
            cal_type = parts[1]
        if len(parts) >= 3:
            title_loc_name = ":".join(cal_title.split(":")[2:]).strip()

    # Resolve provider — try the calendar description (which the manager sets
    # to the staff UUID) first, falling back to title.full_name match for
    # legacy/manually-titled calendars.
    provider_id = ""
    matched_provider = None
    if cal_description:
        for provider in providers:
            pid_str = str(provider.id)
            pid_hex = pid_str.replace("-", "")
            if pid_str in cal_description or pid_hex in cal_description:
                provider_id = pid_str
                matched_provider = provider
                break
    if matched_provider is None and prov_name:
        for provider in providers:
            if provider.full_name == prov_name:
                provider_id = str(provider.id)
                matched_provider = provider
                break

    # Resolve location: prefer explicit name in calendar title; fall back to
    # the matched provider's primary practice location for generic calendars.
    location_id = ""
    if title_loc_name:
        for location in locations:
            if location.full_name == title_loc_name:
                location_id = str(location.id)
                break
    if not location_id and matched_provider is not None:
        primary = getattr(matched_provider, "primary_practice_location", None)
        if primary is not None:
            location_id = str(primary.id)

    # Pick the display tz: user-selected (`view_tz`) overrides the calendar's
    # own tz. Storage stays in UTC; we only adjust for display.
    cal_tz_name = (
        str(event.calendar.timezone) if event.calendar and event.calendar.timezone else "UTC"
    )
    try:
        cal_tz = ZoneInfo(cal_tz_name)
    except Exception:
        cal_tz = ZoneInfo("UTC")
    display_tz = view_tz if view_tz is not None else cal_tz

    def _local_iso(dt):
        if not dt:
            return ""
        local = dt.astimezone(display_tz) if dt.tzinfo else dt
        return local.strftime("%Y-%m-%dT%H:%M")

    rr = event.recurrence or ""
    rr_parts = (
        dict(p.split("=", 1) for p in rr.removeprefix("RRULE:").split(";") if "=" in p)
        if rr
        else {}
    )
    days_of_week = (
        rr_parts.get("BYDAY", "").split(",")
        if rr_parts.get("BYDAY")
        else []
    )

    return {
        "id": str(event.id),
        "title": event.title,
        "location": location_id,
        "provider": provider_id,
        "allowedNoteTypes": [str(nt.id) for nt in event.allowed_note_types.all()],
        "calendar": cal_title,
        "calendarId": str(event.calendar.id) if event.calendar else "",
        "calendarType": cal_type,
        "calendarTimezone": cal_tz_name,
        "startTime": _local_iso(event.starts_at),
        "endTime": _local_iso(event.ends_at),
        "daysOfWeek": days_of_week,
        "recurrence": {
            "type": rr_parts.get("FREQ", ""),
            "interval": int(rr_parts.get("INTERVAL", "0") or 0),
            "endDate": _local_iso(event.recurrence_ends_at),
        },
    }


class CalendarEventsAPI(StaffSessionAuthMixin, SimpleAPIRoute):
    """API endpoint to create, update, or delete calendar events."""

    PATH = "/events"

    def get(self) -> list[Response | Effect]:
        """Return events for the availability manager.

        Query param `tz` (e.g. ``America/Chicago``) controls the display
        timezone — events are serialized as naive HH:MM in that tz, while
        storage stays in UTC. Falls back to the calendar's own timezone
        (and ultimately UTC) when no `tz` is provided.
        """
        tz_param = self.request.query_params.get("tz", "").strip()
        view_tz = None
        if tz_param:
            try:
                view_tz = ZoneInfo(tz_param)
            except Exception:
                view_tz = None

        # Same provider pool as the availability manager UI — schedulable
        # staff per the SCHEDULABLE_STAFF_ROLES secret, plus rooms (RR), so
        # the events list can resolve names for both groups.
        schedulable_roles = parse_schedulable_roles(
            self.secrets.get("SCHEDULABLE_STAFF_ROLES", "")
        )
        role_codes = list({*schedulable_roles, "RR"})
        providers = list(
            Staff.objects
            .filter(active=True, roles__internal_code__in=role_codes)
            .distinct()
        )
        locations = list(PracticeLocation.objects.filter(active=True))
        events = list(
            EventModel.objects.all()
            .select_related("calendar")
            .prefetch_related("allowed_note_types")
        )

        data = [_serialize_event(e, providers, locations, view_tz) for e in events]
        return [
            Response(
                json.dumps(data).encode("utf-8"),
                status_code=HTTPStatus.OK,
                content_type="application/json",
            )
        ]

    def post(self) -> list[Response | Effect]:
        """Create a new calendar event.

        If the body includes a `timezone` field (e.g. ``America/Chicago``),
        it overrides the calendar's tz when interpreting naive HH:MM input.
        Stored values are always converted to UTC.
        """
        body = self.request.json()

        calender_id = body.get("calendar")
        body_tz_name = (body.get("timezone") or "").strip()
        if body_tz_name:
            try:
                cal_tz = ZoneInfo(body_tz_name)
            except Exception:
                cal_tz = _calendar_tz(calender_id)
        else:
            cal_tz = _calendar_tz(calender_id)
        title = body.get("title")
        starts_at = _parse_dt(body.get("startTime"), cal_tz)
        ends_at = _parse_dt(body.get("endTime"), cal_tz)
        recurrence_frequency = body.get("recurrenceFrequency")
        recurrence_interval = body.get("recurrenceInterval")
        recurrence_days = body.get("recurrenceDays")
        recurrence_ends_at = _parse_dt(body.get("recurrenceEndsAt"), cal_tz)
        allowed_note_types = body.get("allowedNoteTypes", [])

        create_calendar_event = Event(
            calendar_id=calender_id,
            title=title,
            starts_at=starts_at,
            ends_at=ends_at,
            recurrence_frequency=EventRecurrence(recurrence_frequency)
            if recurrence_frequency
            else None,
            recurrence_interval=int(recurrence_interval)
            if recurrence_interval is not None
            else None,
            recurrence_days=[DaysOfWeek(day) for day in recurrence_days]
            if recurrence_days
            else None,
            recurrence_ends_at=recurrence_ends_at,
            allowed_note_types=allowed_note_types,
        ).create()

        return [create_calendar_event, Response(status_code=201)]

    def patch(self) -> list[Response | Effect]:
        """Update an existing calendar event."""
        body = self.request.json()

        event_id = body.get("eventId")
        body_tz_name = (body.get("timezone") or "").strip()
        if body_tz_name:
            try:
                cal_tz = ZoneInfo(body_tz_name)
            except Exception:
                cal_tz = _calendar_tz_for_event(event_id)
        else:
            cal_tz = _calendar_tz_for_event(event_id)
        title = body.get("title")
        starts_at = _parse_dt(body.get("startTime"), cal_tz)
        ends_at = _parse_dt(body.get("endTime"), cal_tz)
        recurrence_frequency = body.get("recurrenceFrequency")
        recurrence_interval = body.get("recurrenceInterval")
        recurrence_days = body.get("recurrenceDays")
        recurrence_ends_at = _parse_dt(body.get("recurrenceEndsAt"), cal_tz)
        allowed_note_types = body.get("allowedNoteTypes", [])

        update_calendar_event = Event(
            event_id=event_id,
            title=title,
            starts_at=starts_at,
            ends_at=ends_at,
            recurrence_frequency=EventRecurrence(recurrence_frequency)
            if recurrence_frequency
            else None,
            recurrence_interval=int(recurrence_interval)
            if recurrence_interval is not None
            else None,
            recurrence_days=[DaysOfWeek(day) for day in recurrence_days]
            if recurrence_days
            else None,
            recurrence_ends_at=recurrence_ends_at,
            allowed_note_types=allowed_note_types,
        ).update()

        return [update_calendar_event, Response(status_code=200)]

    def delete(self) -> list[Response | Effect]:
        """Delete an existing calendar event."""
        body = self.request.json()

        event_id = body.get("eventId")

        delete_calendar_event = Event(event_id=event_id).delete()

        return [delete_calendar_event, Response(status_code=200)]
