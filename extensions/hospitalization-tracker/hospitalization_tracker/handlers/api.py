from __future__ import annotations

import uuid as uuid_module
from datetime import datetime, timezone
from http import HTTPStatus

from canvas_sdk.commands.commands.custom_command import CustomCommand
from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.note import Note
from canvas_sdk.v1.data.patient import Patient

from hospitalization_tracker.models import Hospitalization


class HospitalizationSummaryCommand(CustomCommand):
    """Custom command representing an inpatient stay history in a note."""

    class Meta:
        schema_key = "hospitalizationSummary"


class HospitalizationAPI(StaffSessionAuthMixin, SimpleAPI):
    """API for the hospitalization tracker: form, submission, and list."""

    PREFIX = ""

    @api.get("/app/form")
    def get_form(self) -> list[Response | Effect]:
        """Render the hospitalization entry form HTML page."""
        patient_id = self.request.query_params.get("patient_id", "")
        note_id = self.request.query_params.get("note_id", "")
        if not patient_id or not note_id:
            return [
                JSONResponse(
                    {"error": "patient_id and note_id are required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        content = render_to_string(
            "templates/hospitalization_form.html",
            {
                "patient_id": patient_id,
                "note_id": note_id,
            },
        )
        return [HTMLResponse(content=content)]

    @api.post("/hospitalizations")
    def create_hospitalization(self) -> list[Response | Effect]:
        """Create a hospitalization record and insert a CustomCommand into the note."""
        body = self.request.json() or {}

        patient_id: str = body.get("patient_id", "")
        note_id: str = body.get("note_id", "")
        admission_date_str: str = body.get("admission_date", "")
        hospital_name: str = body.get("hospital_name", "")
        reason_for_admission: str = body.get("reason_for_admission", "")

        if not patient_id or not note_id:
            return [
                JSONResponse(
                    {"error": "patient_id and note_id are required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        if not admission_date_str:
            return [
                JSONResponse(
                    {"error": "admission_date is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        if not hospital_name:
            return [
                JSONResponse(
                    {"error": "hospital_name is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        if not reason_for_admission:
            return [
                JSONResponse(
                    {"error": "reason_for_admission is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        try:
            patient = Patient.objects.get(id=patient_id)
        except Patient.DoesNotExist:
            return [
                JSONResponse(
                    {"error": "Patient not found"},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        try:
            note = Note.objects.get(id=note_id)
        except Note.DoesNotExist:
            return [
                JSONResponse(
                    {"error": "Note not found"},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        discharge_date_str: str = body.get("discharge_date", "")
        discharge_date = (
            datetime.strptime(discharge_date_str, "%Y-%m-%d").date()
            if discharge_date_str
            else None
        )

        icu_stay: bool = bool(body.get("icu_stay", False))
        icu_duration_raw = body.get("icu_duration_days")
        icu_duration_days: int | None = (
            int(icu_duration_raw) if icu_duration_raw is not None and icu_duration_raw != "" else None
        )

        hospitalization = Hospitalization(
            patient=patient,
            admission_date=datetime.strptime(admission_date_str, "%Y-%m-%d").date(),
            discharge_date=discharge_date,
            hospital_name=hospital_name,
            reason_for_admission=reason_for_admission,
            principal_diagnosis=body.get("principal_diagnosis", ""),
            icu_stay=icu_stay,
            icu_duration_days=icu_duration_days,
            discharge_disposition=body.get("discharge_disposition", ""),
            readmission_within_30_days=bool(body.get("readmission_within_30_days", False)),
            treating_physician=body.get("treating_physician", ""),
            notes=body.get("notes", ""),
        )
        hospitalization.save()

        note_uuid = str(note.id)
        command_uuid = str(uuid_module.uuid4())

        command_content = render_to_string(
            "templates/hospitalization_command.html",
            {"hospitalization": hospitalization},
        )

        command = HospitalizationSummaryCommand(
            content=command_content,
            print_content=command_content,
        )
        command.note_uuid = note_uuid
        command.command_uuid = command_uuid

        return [
            command.originate(),
            JSONResponse(
                {"success": True, "id": hospitalization.dbid},
                status_code=HTTPStatus.CREATED,
            ),
        ]

    @api.get("/hospitalizations")
    def list_hospitalizations(self) -> list[Response | Effect]:
        """Return all hospitalization records for a given patient_id."""
        patient_id = self.request.query_params.get("patient_id", "")
        if not patient_id:
            return [
                JSONResponse(
                    {"error": "patient_id is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        hospitalizations = list(
            Hospitalization.objects.filter(patient__id=patient_id).order_by("-admission_date")
        )

        return [
            JSONResponse(
                {
                    "hospitalizations": [
                        _serialize_hospitalization(h) for h in hospitalizations
                    ]
                }
            )
        ]


def _serialize_hospitalization(h: Hospitalization) -> dict[str, object]:
    """Serialize a Hospitalization instance to a JSON-compatible dict."""
    return {
        "id": h.dbid,
        "admission_date": h.admission_date.isoformat() if h.admission_date else None,
        "discharge_date": h.discharge_date.isoformat() if h.discharge_date else None,
        "hospital_name": h.hospital_name,
        "reason_for_admission": h.reason_for_admission,
        "principal_diagnosis": h.principal_diagnosis,
        "icu_stay": h.icu_stay,
        "icu_duration_days": h.icu_duration_days,
        "discharge_disposition": h.discharge_disposition,
        "readmission_within_30_days": h.readmission_within_30_days,
        "treating_physician": h.treating_physician,
        "notes": h.notes,
        "length_of_stay_days": h.length_of_stay_days,
        "created_at": h.created_at.isoformat() if h.created_at else None,
    }
