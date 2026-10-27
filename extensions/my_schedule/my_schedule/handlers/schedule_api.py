"""My Schedule API: the page, the logged-in staff member's own appointments, and optional actions.

Every request is scoped on the server to the staff member in the
canvas-logged-in-user-id header. The page never sends a provider, so there is
no parameter to tamper with. Actions are off unless their setting is yes, and
only work on the caller's own appointments; anyone else's appointment answers
404, exactly like one that doesn't exist.
"""

import uuid
from datetime import datetime, timedelta, timezone
from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.note.appointment import Appointment as AppointmentEffect
from canvas_sdk.effects.note.note import Note as NoteEffect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.appointment import Appointment, AppointmentProgressStatus
from canvas_sdk.v1.data.note import CurrentNoteStateEvent, NoteStates

from my_schedule.handlers.access import parse_flag

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))

# The month view asks for a 6-week grid; anything wider is refused.
MAX_RANGE = timedelta(days=43)

# Statuses staff can set from the page. No-show and cancel have their own actions.
SETTABLE_STATUSES = {
    AppointmentProgressStatus.UNCONFIRMED,
    AppointmentProgressStatus.ATTEMPTED,
    AppointmentProgressStatus.CONFIRMED,
    AppointmentProgressStatus.ARRIVED,
    AppointmentProgressStatus.ROOMED,
    AppointmentProgressStatus.EXITED,
}
CANCELLABLE_NOTE_STATES = {NoteStates.BOOKED, NoteStates.CONVERTED}
NOSHOW_NOTE_STATES = {NoteStates.BOOKED, NoteStates.REVERTED}


def _parse_iso(value: str) -> datetime:
    """Parse an ISO-8601 datetime with a time zone. Accepts a trailing 'Z' as UTC."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("datetime must include a time zone")
    return parsed


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except (TypeError, ValueError):
        return False
    return True


def _note_state(appt: Appointment) -> str | None:
    try:
        return appt.note.current_state.state
    except CurrentNoteStateEvent.DoesNotExist:
        return None


def _serialize_appointment(appt: Appointment) -> dict:
    patient = appt.patient
    return {
        "id": str(appt.id),
        "start_time": appt.start_time.isoformat() if appt.start_time else None,
        "duration_minutes": appt.duration_minutes,
        "patient_id": str(patient.id) if patient else "",
        "patient_name": f"{patient.first_name} {patient.last_name}".strip() if patient else "",
        "appointment_type": appt.note_type.name if appt.note_type else "",
        "reason_for_visit": appt.description or "",
        "location": appt.location.full_name if appt.location else "",
        "status": appt.status or "",
    }


def _error(message: str, status: HTTPStatus) -> list[Response | Effect]:
    return [JSONResponse({"error": message}, status_code=status)]


class MyScheduleAPI(StaffSessionAuthMixin, SimpleAPI):
    """Serves My Schedule. Staff only, own appointments only."""

    PREFIX = "/app"

    def _staff_id(self) -> str:
        return self.request.headers["canvas-logged-in-user-id"]

    def _actions(self) -> dict[str, bool]:
        return {
            "status": parse_flag(self.secrets.get("ALLOW_STATUS_UPDATES"), default=False),
            "cancel": parse_flag(self.secrets.get("ALLOW_CANCEL"), default=False),
            "noshow": parse_flag(self.secrets.get("ALLOW_NO_SHOW"), default=False),
        }

    def _own_appointment(self) -> Appointment | None:
        """The appointment in the path, only if the caller is its provider."""
        appointment_id = self.request.path_params.get("appointment_id", "")
        if not _is_uuid(appointment_id):
            return None
        return (
            Appointment.objects.filter(
                id=appointment_id,
                provider__id=self._staff_id(),
                entered_in_error__isnull=True,
            )
            .select_related("note")
            .first()
        )

    @api.get("/")
    def index(self) -> list[Response | Effect]:
        actions = self._actions()
        context = {
            "cache_bust": _CACHE_BUST,
            "allow_status": "true" if actions["status"] else "false",
            "allow_cancel": "true" if actions["cancel"] else "false",
            "allow_noshow": "true" if actions["noshow"] else "false",
        }
        return [
            HTMLResponse(
                render_to_string("static/index.html", context), status_code=HTTPStatus.OK
            )
        ]

    @api.get("/appointments")
    def appointments(self) -> list[Response | Effect]:
        start_str = self.request.query_params.get("start")
        end_str = self.request.query_params.get("end")
        if not start_str or not end_str:
            return _error("start and end are required", HTTPStatus.BAD_REQUEST)
        try:
            start = _parse_iso(start_str)
            end = _parse_iso(end_str)
        except ValueError:
            return _error(
                "start and end must be ISO-8601 datetimes with a time zone",
                HTTPStatus.BAD_REQUEST,
            )
        if end <= start or end - start > MAX_RANGE:
            return _error("the date range must be between 0 and 43 days", HTTPStatus.BAD_REQUEST)

        appts = (
            Appointment.objects.filter(
                provider__id=self._staff_id(),
                start_time__gte=start,
                start_time__lt=end,
                entered_in_error__isnull=True,
            )
            .exclude(status=AppointmentProgressStatus.CANCELLED)
            .exclude(note__current_state__state=NoteStates.DELETED)
            .select_related("patient", "note_type", "location")
            .order_by("start_time")
        )
        return [JSONResponse({"appointments": [_serialize_appointment(a) for a in appts]})]

    @api.post("/appointment/<appointment_id>/status")
    def update_status(self) -> list[Response | Effect]:
        if not self._actions()["status"]:
            return _error("Status updates are turned off", HTTPStatus.FORBIDDEN)
        appt = self._own_appointment()
        if appt is None:
            return _error("Appointment not found", HTTPStatus.NOT_FOUND)
        try:
            body = self.request.json()
        except ValueError:
            return _error("Invalid JSON", HTTPStatus.BAD_REQUEST)
        new_status = body.get("status") if isinstance(body, dict) else None
        if not isinstance(new_status, str) or new_status not in SETTABLE_STATUSES:
            return _error("Invalid status", HTTPStatus.BAD_REQUEST)
        effect = AppointmentEffect(
            instance_id=str(appt.id), status=AppointmentProgressStatus(new_status)
        )
        return [effect.update(), JSONResponse({"ok": True})]

    @api.post("/appointment/<appointment_id>/cancel")
    def cancel(self) -> list[Response | Effect]:
        if not self._actions()["cancel"]:
            return _error("Cancelling is turned off", HTTPStatus.FORBIDDEN)
        appt = self._own_appointment()
        if appt is None:
            return _error("Appointment not found", HTTPStatus.NOT_FOUND)
        if not appt.note_id:
            return _error("This appointment can't be cancelled here", HTTPStatus.BAD_REQUEST)
        if _note_state(appt) not in CANCELLABLE_NOTE_STATES:
            return _error("This appointment can no longer be cancelled", HTTPStatus.CONFLICT)
        return [AppointmentEffect(instance_id=str(appt.id)).cancel(), JSONResponse({"ok": True})]

    @api.post("/appointment/<appointment_id>/noshow")
    def noshow(self) -> list[Response | Effect]:
        if not self._actions()["noshow"]:
            return _error("No-show is turned off", HTTPStatus.FORBIDDEN)
        appt = self._own_appointment()
        if appt is None:
            return _error("Appointment not found", HTTPStatus.NOT_FOUND)
        if not appt.note_id:
            return _error("This appointment can't be marked no-show", HTTPStatus.BAD_REQUEST)
        if _note_state(appt) not in NOSHOW_NOTE_STATES:
            return _error("This appointment can't be marked no-show now", HTTPStatus.CONFLICT)
        return [NoteEffect(instance_id=str(appt.note.id)).no_show(), JSONResponse({"ok": True})]

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
