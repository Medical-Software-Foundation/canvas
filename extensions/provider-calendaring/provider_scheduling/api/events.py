import arrow

from canvas_sdk.effects import Effect
from canvas_sdk.effects.calendar import (
    DaysOfWeek,
    Event,
    EventRecurrence,
)
from canvas_sdk.effects.simple_api import Response
from canvas_sdk.handlers.simple_api import SimpleAPIRoute, StaffSessionAuthMixin


class CalendarEventsAPI(StaffSessionAuthMixin, SimpleAPIRoute):
    """API endpoint to create, update, or delete calendar events."""

    PATH = "/events"

    def post(self) -> list[Response | Effect]:
        """Create a new calendar event."""
        body = self.request.json()

        calender_id = body.get("calendar")
        title = body.get("title")
        starts_at = arrow.get(body.get("startTime")).datetime
        ends_at = arrow.get(body.get("endTime")).datetime
        recurrence_frequency = body.get("recurrenceFrequency")
        recurrence_interval = body.get("recurrenceInterval")
        recurrence_days = body.get("recurrenceDays")
        recurrence_ends_at = (
            arrow.get(body.get("recurrenceEndsAt")).datetime
            if body.get("recurrenceEndsAt")
            else None
        )
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
        title = body.get("title")
        starts_at = arrow.get(body.get("startTime")).datetime
        ends_at = arrow.get(body.get("endTime")).datetime
        recurrence_frequency = body.get("recurrenceFrequency")
        recurrence_interval = body.get("recurrenceInterval")
        recurrence_days = body.get("recurrenceDays")
        recurrence_ends_at = (
            arrow.get(body.get("recurrenceEndsAt")).datetime
            if body.get("recurrenceEndsAt")
            else None
        )
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
