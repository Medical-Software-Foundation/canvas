from datetime import datetime, timezone
from http import HTTPStatus

from pydantic import ValidationError

from canvas_sdk.commands.commands.vitals import VitalsCommand
from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))

_INT_FIELDS = (
    "blood_pressure_systole",
    "blood_pressure_diastole",
    "pulse",
    "respiration_rate",
    "oxygen_saturation",
    "weight_lbs",
    "height",
    "waist_circumference",
)
_FLOAT_FIELDS = ("body_temperature",)
_STR_FIELDS = ("note",)
_SUPPORTED_FIELDS = _INT_FIELDS + _FLOAT_FIELDS + _STR_FIELDS


def _coerce_payload(body: dict) -> tuple[dict, str | None]:
    """Coerce supported fields to their expected types. Unknown fields are ignored."""
    coerced: dict = {}
    for field in _INT_FIELDS:
        if field not in body or body[field] in (None, ""):
            continue
        try:
            coerced[field] = int(body[field])
        except (TypeError, ValueError):
            return {}, f"{field} must be an integer"
    for field in _FLOAT_FIELDS:
        if field not in body or body[field] in (None, ""):
            continue
        try:
            coerced[field] = float(body[field])
        except (TypeError, ValueError):
            return {}, f"{field} must be a number"
    for field in _STR_FIELDS:
        if field not in body or body[field] in (None, ""):
            continue
        coerced[field] = str(body[field])
    return coerced, None


class VitalsAPI(StaffSessionAuthMixin, SimpleAPI):
    """Serves the vitals entry UI and originates a Vitals command on submit."""

    PREFIX = "/app"

    @api.get("/")
    def index(self) -> list[Response | Effect]:
        return [
            HTMLResponse(
                render_to_string("static/index.html", {"cache_bust": _CACHE_BUST}),
                status_code=HTTPStatus.OK,
            )
        ]

    @api.post("/vitals")
    def submit_vitals(self) -> list[Response | Effect]:
        note_id = self.request.query_params.get("note_id", "").strip()
        if not note_id:
            return [
                JSONResponse(
                    {"error": "note_id query param is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        body = self.request.json() or {}
        fields, error = _coerce_payload(body)
        if error:
            return [JSONResponse({"error": error}, status_code=HTTPStatus.BAD_REQUEST)]
        if not fields:
            return [
                JSONResponse(
                    {"error": "at least one vital is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        try:
            command = VitalsCommand(note_uuid=note_id, **fields)
        except ValidationError as e:
            return [
                JSONResponse(
                    {"error": "invalid vitals", "detail": e.errors()},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        return [
            command.originate(),
            JSONResponse({"status": "originated"}, status_code=HTTPStatus.ACCEPTED),
        ]

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
