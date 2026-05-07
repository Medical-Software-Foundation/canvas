"""SimpleAPI for the patient-profile companion editor.

Endpoints (all under /plugin-io/api/provider_patient_profile_companion/app/):

| GET  /                  | HTML shell                                      |
| GET  /main.js           | JS                                              |
| GET  /styles.css        | CSS                                             |
| GET  /data.json         | Current values + sex_at_birth options           |
| POST /save              | Patient.update() with the submitted identity    |
|                         | fields.                                         |
"""

from datetime import date, datetime, timezone
from http import HTTPStatus
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.patient import Patient as PatientEffect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.common import PersonSex
from canvas_sdk.v1.data.patient import Patient

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))

_SEX_AT_BIRTH_CHOICES = [
    {"value": value, "label": label or "Blank"}
    for value, label in PersonSex.choices
]


def _serialize_patient(patient: Patient) -> dict[str, Any]:
    """Build the form's initial state from a Patient row."""
    return {
        "patient_id": patient.id,
        "fields": {
            "first_name": patient.first_name or "",
            "middle_name": patient.middle_name or "",
            "last_name": patient.last_name or "",
            "prefix": patient.prefix or "",
            "suffix": patient.suffix or "",
            "nickname": patient.nickname or "",
            "birthdate": patient.birth_date.isoformat() if patient.birth_date else "",
            "sex_at_birth": patient.sex_at_birth or "",
            "social_security_number": patient.social_security_number or "",
        },
        "options": {
            "sex_at_birth": _SEX_AT_BIRTH_CHOICES,
        },
    }


def _parse_birthdate(raw: Any) -> tuple[date | None, str | None]:
    """Parse a birthdate string; return (date, error)."""
    if raw is None or raw == "":
        return None, "birthdate is required"
    if not isinstance(raw, str):
        return None, "birthdate must be a string"
    try:
        return date.fromisoformat(raw), None
    except ValueError:
        return None, "birthdate must be in YYYY-MM-DD format"


def _build_patient_effect(
    patient_id: str, fields: dict[str, Any]
) -> tuple[PatientEffect | None, str | None]:
    """Translate the submitted identity fields into a Patient update effect."""
    birthdate, err = _parse_birthdate(fields.get("birthdate"))
    if err:
        return None, err

    sex_at_birth = fields.get("sex_at_birth", "")
    if sex_at_birth not in {choice.value for choice in PersonSex}:
        return None, "sex_at_birth must be one of F, M, O, UNK, or blank"

    first_name = (fields.get("first_name") or "").strip()
    last_name = (fields.get("last_name") or "").strip()
    if not first_name:
        return None, "first_name is required"
    if not last_name:
        return None, "last_name is required"

    effect = PatientEffect(
        patient_id=patient_id,
        first_name=first_name,
        last_name=last_name,
        middle_name=(fields.get("middle_name") or "").strip(),
        prefix=(fields.get("prefix") or "").strip(),
        suffix=(fields.get("suffix") or "").strip(),
        nickname=(fields.get("nickname") or "").strip(),
        birthdate=birthdate,
        sex_at_birth=PersonSex(sex_at_birth),
        social_security_number=(fields.get("social_security_number") or "").strip(),
    )
    return effect, None


class ProfileAPI(StaffSessionAuthMixin, SimpleAPI):
    """Serves the profile-editor shell, JSON data, and save."""

    PREFIX = "/app"

    @api.get("/")
    def index(self) -> list[Response | Effect]:
        return [
            HTMLResponse(
                render_to_string("static/index.html", {"cache_bust": _CACHE_BUST}),
                status_code=HTTPStatus.OK,
                headers={"Cache-Control": "no-store"},
            )
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

    @api.get("/data.json")
    def data(self) -> list[Response | Effect]:
        patient_id = (self.request.query_params.get("patient_id") or "").strip()
        if not patient_id:
            return [
                JSONResponse(
                    {"error": "patient_id query param is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        try:
            patient = Patient.objects.get(id=patient_id)
        except Patient.DoesNotExist:
            return [JSONResponse({"error": "patient not found"}, status_code=HTTPStatus.NOT_FOUND)]
        return [JSONResponse(_serialize_patient(patient))]

    @api.post("/save")
    def save(self) -> list[Response | Effect]:
        body = self.request.json() or {}
        patient_id = (body.get("patient_id") or "").strip()
        if not patient_id:
            return [
                JSONResponse(
                    {"error": "patient_id is required"}, status_code=HTTPStatus.BAD_REQUEST
                )
            ]
        try:
            Patient.objects.get(id=patient_id)
        except Patient.DoesNotExist:
            return [JSONResponse({"error": "patient not found"}, status_code=HTTPStatus.NOT_FOUND)]

        fields = body.get("fields") or {}
        if not isinstance(fields, dict):
            return [
                JSONResponse(
                    {"error": "fields must be an object"}, status_code=HTTPStatus.BAD_REQUEST
                )
            ]

        effect, err = _build_patient_effect(patient_id, fields)
        if err or effect is None:
            return [JSONResponse({"error": err}, status_code=HTTPStatus.BAD_REQUEST)]

        # The effect is applied after the response is returned, so the client
        # re-fetches /data.json on success rather than trusting this body.
        return [effect.update(), JSONResponse({"ok": True})]
