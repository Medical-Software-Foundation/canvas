import arrow

from base64 import b64encode, b64decode
from hashlib import sha256
from http import HTTPStatus

from canvas_sdk.v1.data.appointment import Appointment
from canvas_sdk.v1.data.staff import Staff
from canvas_sdk.v1.data.practicelocation import PracticeLocation
from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import Response, HTMLResponse
from canvas_sdk.handlers.simple_api import Credentials, StaffSessionAuthMixin, SimpleAPI, api

from ical.icalendar import Calendar, Event

from canvas_sdk.templates import render_to_string


class Information(StaffSessionAuthMixin, SimpleAPI):
    def calendar_opaque_token_from_identifier(self, identifier: str) -> str:
        # The calendar identifier is:
        # base64 encoded
        #   colon separated
        #       first part is SHA256(CONCAT(salt, id)) 
        #       second part is id
        computed_hash = sha256(self.secrets['CALENDAR_LINK_SALT__EXISTING_LINKS_BECOME_INVALID_IF_CHANGED'].encode() + identifier.encode()).hexdigest()
        encoded_token = b64encode(f"{computed_hash}:{identifier}".encode()).decode()
        return encoded_token

    @api.get("/calendars")
    def ical_links(self) -> list[Response | Effect]:
        logged_in_staff = Staff.objects.get(id=self.request.headers["canvas-logged-in-user-id"])
        requested_uri = self.context.get("absolute_uri")
        base_url = requested_uri.split('/ical/')[0]

        staff_calendar_opaque_token = self.calendar_opaque_token_from_identifier(logged_in_staff.id)
        personal_calendar_url = f"{base_url}/ical/provider/{staff_calendar_opaque_token}"

        locations = []
        for location in PracticeLocation.objects.filter(active=True).values("id", "short_name"):
            location_calendar_opaque_token = self.calendar_opaque_token_from_identifier(str(location.get("id")))
            location_calendar_url = f"{base_url}/ical/location/{location_calendar_opaque_token}"
            locations.append({
                "label": location.get("short_name"),
                "url": location_calendar_url,
            })


        context = {
            "logged_in_staff": logged_in_staff,
            "personal_calendar_url": personal_calendar_url,
            "location_calendars": locations,
        }
        return [
            HTMLResponse(
                render_to_string("templates/index.html", context),
                status_code=HTTPStatus.OK,
            )
        ]


class Calendars(SimpleAPI):
    def authenticate(self, credentials: Credentials) -> bool:
        # Authentication is handled in `get_validated_calendar_identifier`,
        # where we assert a provided hash matches one we calculate ourselves
        # for the given calendar identifier.
        return True

    @api.get("/location/<id>")
    def location_calendar(self) -> list[Response | Effect]:
        encoded_calendar_identifier = self.request.path_params["id"]
        location_id = self.get_validated_calendar_identifier(encoded_calendar_identifier)
        if location_id is None or not PracticeLocation.objects.filter(id=location_id).exists():
            return self.calendar_not_found_response()

        location = PracticeLocation.objects.get(id=location_id)
        calendar_name = f"Location Appointments {location.short_name}"

        one_month_ago = arrow.utcnow().shift(months=-1).datetime
        one_year_hence = arrow.utcnow().shift(years=1).datetime
        appt_data = Appointment.objects.filter(location__id=location_id).filter(start_time__gte=one_month_ago, start_time__lte=one_year_hence).values(
            "id",
            "note_type__display",
            "start_time",
            "duration_minutes",
            "location__short_name",
            "status",
            "provider__first_name",
            "provider__last_name",
            "provider__user__email",
        )

        ical = Calendar()

        for appt in appt_data:
            ical.add_event(Event({
                "id": appt.get("id"),
                "event_title": appt.get("note_type__display"),
                "start_time": appt.get("start_time"),
                "duration_minutes": appt.get("duration_minutes"),
                "location": appt.get("location__short_name"),
                "status": appt.get("status"),
                "organizer_name": " ".join([
                    appt.get("provider__first_name"),
                    appt.get("provider__last_name")
                ]),
                "organizer_email": appt.get("provider__user__email"),
            }))

        return [
            Response(
                ical.to_vcalendar().encode(),
                status_code=HTTPStatus.OK,
                headers={
                    "Content-Disposition": f'attachment; filename="{calendar_name}.ics"'
                },
                content_type="text/calendar",
            )
        ]

    @api.get("/provider/<id>")
    def provider_calendar(self) -> list[Response | Effect]:
        encoded_calendar_identifier = self.request.path_params["id"]
        provider_id = self.get_validated_calendar_identifier(encoded_calendar_identifier)
        if provider_id is None or not Staff.objects.filter(id=provider_id).exists():
            return self.calendar_not_found_response()

        provider = Staff.objects.get(id=provider_id)
        calendar_name = f"Provider Appointments {provider.first_name} {provider.last_name}"

        one_month_ago = arrow.utcnow().shift(months=-1).datetime
        one_year_hence = arrow.utcnow().shift(years=1).datetime
        appt_data = Appointment.objects.filter(provider__id=provider_id).filter(start_time__gte=one_month_ago, start_time__lte=one_year_hence).values(
            "id",
            "note_type__display",
            "start_time",
            "duration_minutes",
            "location__short_name",
            "status",
            "provider__first_name",
            "provider__last_name",
            "provider__user__email",
        )

        ical = Calendar()

        for appt in appt_data:
            ical.add_event(Event({
                "id": appt.get("id"),
                "event_title": appt.get("note_type__display"),
                "start_time": appt.get("start_time"),
                "duration_minutes": appt.get("duration_minutes"),
                "location": appt.get("location__short_name"),
                "status": appt.get("status"),
                "organizer_name": " ".join([
                    appt.get("provider__first_name"),
                    appt.get("provider__last_name")
                ]),
                "organizer_email": appt.get("provider__user__email"),
            }))

        return [
            Response(
                ical.to_vcalendar().encode(),
                status_code=HTTPStatus.OK,
                headers={
                    "Content-Disposition": f'attachment; filename="{calendar_name}.ics"'
                },
                content_type="text/calendar",
            )
        ]

    def calendar_not_found_response(self) -> Response:
        return [
            Response(
                'Calendar not found'.encode(),
                status_code=HTTPStatus.NOT_FOUND,
                content_type="text/plain",
            )
        ]

    def get_validated_calendar_identifier(self, encoded_param: str) -> str | None:
        # We expect the calendar identifier to be
        # base64 encoded
        #   colon separated
        #       first part is SHA256(CONCAT(salt, id)) 
        #       second part is id
        # So we:
        # 1. decode the query param
        # 2. get the pieces by splitting on ':' (and expect only 2)
        # 3. use the provided plaintext id and configured salt to generate a
        #    sha256 hash
        # 4. compare the hash we computed to the one they provided
        
        decoded_param = b64decode(encoded_param.encode()).decode().strip()
        provided_hash, plain_id = decoded_param.split(':')
        computed_hash = sha256(self.secrets['CALENDAR_LINK_SALT__EXISTING_LINKS_BECOME_INVALID_IF_CHANGED'].encode() + plain_id.encode()).hexdigest()
        if provided_hash == computed_hash:
            return plain_id
        return None
