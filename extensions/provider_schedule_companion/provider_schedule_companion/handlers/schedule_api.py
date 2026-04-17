from datetime import datetime
from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SessionCredentials, SimpleAPI, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.appointment import Appointment


def _parse_iso(value: str) -> datetime:
    """Parse an ISO-8601 datetime. Accepts trailing 'Z' as UTC."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _serialize_appointment(appt: Appointment) -> dict:
    patient = appt.patient
    note_type = appt.note_type
    return {
        "id": str(appt.id),
        "start_time": appt.start_time.isoformat() if appt.start_time else None,
        "duration_minutes": appt.duration_minutes,
        "patient_id": str(patient.id) if patient else "",
        "patient_name": (
            f"{patient.first_name} {patient.last_name}".strip() if patient else ""
        ),
        "appointment_type": note_type.name if note_type else "",
        "reason_for_visit": appt.description or "",
        "status": appt.status or "",
    }


class ScheduleAPI(SimpleAPI):
    """Serves the schedule companion UI and JSON data."""

    PREFIX = "/app"

    def authenticate(self, credentials: SessionCredentials) -> bool:
        return credentials.logged_in_user is not None

    @api.get("/")
    def index(self) -> list[Response | Effect]:
        return [
            HTMLResponse(
                render_to_string("static/index.html", {}),
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/appointments")
    def appointments(self) -> list[Response | Effect]:
        staff_id = self.request.headers["canvas-logged-in-user-id"]
        start_str = self.request.query_params.get("start")
        end_str = self.request.query_params.get("end")

        if not start_str or not end_str:
            return [
                JSONResponse(
                    {"error": "start and end ISO-8601 query params are required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        try:
            start = _parse_iso(start_str)
            end = _parse_iso(end_str)
        except ValueError:
            return [
                JSONResponse(
                    {"error": "start and end must be ISO-8601 datetimes"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        appts = (
            Appointment.objects.filter(
                provider__id=staff_id,
                start_time__gte=start,
                start_time__lt=end,
            )
            .select_related("patient", "note_type")
            .order_by("start_time")
        )

        return [JSONResponse({"appointments": [_serialize_appointment(a) for a in appts]})]

    @api.get("/main.js")
    def main_js(self) -> list[Response | Effect]:
        return [
            Response(
                render_to_string("static/main.js").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/javascript",
            )
        ]

    @api.get("/styles.css")
    def styles_css(self) -> list[Response | Effect]:
        return [
            Response(
                render_to_string("static/styles.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
            )
        ]
