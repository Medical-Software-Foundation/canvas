import json
from uuid import uuid4

from canvas_sdk.effects import Effect
from canvas_sdk.effects.calendar import Calendar as CalendarEffect
from canvas_sdk.effects.calendar import CalendarType
from canvas_sdk.effects.simple_api import Response
from canvas_sdk.handlers.simple_api import SimpleAPIRoute, StaffSessionAuthMixin
from canvas_sdk.v1.data import Calendar
from django.db.models import Q

from scheduling_with_rooms.utils.calendar_availability import parse_calendar_title


def _json_response(body: dict, status: int) -> Response:
    """Return a Response with content_type=application/json so clients parse it."""
    return Response(
        json.dumps(body).encode("utf-8"),
        status_code=status,
        content_type="application/json",
    )


def _existing_calendar_id(
    provider: str | None,
    calendar_type: CalendarType,
    location_name: str | None,
) -> str | None:
    """Return the id of an existing calendar for this staff + type + location.

    Binds on the staff UUID embedded in the calendar ``description`` plus the
    type and location parsed from the title — the same resilient lookup the
    scheduler uses (``_staff_calendars``). The previous exact-title match broke
    whenever the staff's display name in the title differed from the posted
    ``providerName`` (e.g. a credential suffix like "MD"), so the retrieve
    always missed and a brand-new calendar was minted on every call — that's
    what produced ~50 duplicate "John Harris MD: Admin" calendars.

    Returns the highest-pk match for determinism when duplicates already exist,
    or ``None`` when nothing matches (caller falls back / creates).
    """
    if not provider:
        return None

    pid = str(provider)
    pid_hex = pid.replace("-", "")
    type_str = str(calendar_type)
    target_loc = (location_name or "").strip().lower()

    candidates = Calendar.objects.filter(
        Q(description__icontains=pid) | Q(description__icontains=pid_hex),
        title__icontains=f": {type_str}",
    ).order_by("pk")

    match_id: str | None = None
    for cal in candidates:
        _, _, cal_location = parse_calendar_title(cal.title)
        if (cal_location or "").strip().lower() == target_loc:
            match_id = str(cal.id)
    return match_id


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

        # Resilient lookup by staff UUID + type + location (survives display-name
        # formatting differences). Fall back to the legacy exact-title match for
        # calendars created before descriptions carried the staff UUID.
        calendar_id = _existing_calendar_id(provider, calendar_type, location_name)
        if not calendar_id:
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
            return [_json_response({"calendarId": str(calendar_id)}, 200)]

        calendar_id = str(uuid4())
        description = body.get("description")

        calendar = CalendarEffect(
            id=calendar_id,
            provider=provider,
            type=calendar_type,
            location=location if location else None,
            description=description,
        ).create()

        return [calendar, _json_response({"calendarId": calendar_id}, 201)]
