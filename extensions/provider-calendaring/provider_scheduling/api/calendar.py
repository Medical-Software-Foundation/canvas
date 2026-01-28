import json
from uuid import uuid4

from canvas_sdk.effects import Effect
from canvas_sdk.effects.calendar import Calendar as CalendarEffect
from canvas_sdk.effects.calendar import CalendarType
from canvas_sdk.effects.simple_api import Response
from canvas_sdk.handlers.simple_api import SimpleAPIRoute, StaffSessionAuthMixin
from canvas_sdk.v1.data import Calendar


class CalendarAPI(StaffSessionAuthMixin, SimpleAPIRoute):
    """API endpoint to create or retrieve calendars."""

    PATH = "/calendar"

    def post(self) -> list[Response | Effect]:
        """Create or retrieve a calendar."""
        calendar_type = CalendarType.Clinic

        body = self.request.json()
        provider = body.get("provider")
        provider_name = body.get("providerName")
        location = body.get("location")
        location_name = body.get("locationName")
        type = body.get("type")

        if type == "Clinic":
            calendar_type = CalendarType.Clinic
        elif type == "Admin":
            calendar_type = CalendarType.Administrative

        calendar_id = (
            Calendar.objects.for_calendar_name(
                provider_name=provider_name,
                calendar_type=calendar_type,
                location=location_name if location_name else None,
            )
            .values_list("id", flat=True)
            .last()
        )

        if calendar_id:
            response_data = json.dumps({"calendarId": str(calendar_id)}).encode("utf-8")

            return [Response(status_code=200, content=response_data)]
        else:
            calendar_id = str(uuid4())
            description = body.get("description")

            calendar = CalendarEffect(
                id=calendar_id,
                provider=provider,
                type=calendar_type,
                location=location if location else None,
                description=description,
            ).create()

            response_data = json.dumps({"calendarId": calendar_id}).encode("utf-8")

            return [calendar, Response(status_code=201, content=response_data)]
