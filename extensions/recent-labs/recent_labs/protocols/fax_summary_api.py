"""SimpleAPI route that builds a faxable lab-summary note."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import ValidationError

from canvas_sdk.commands import CustomCommand
from canvas_sdk.effects import Effect
from canvas_sdk.effects.note import Note
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPIRoute, StaffSessionAuthMixin
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data import NoteType, Patient, PracticeLocation
from logger import log

from recent_labs.labs import get_recent_results_by_test

# Header carrying the logged-in staff member's id on SimpleAPI session requests.
LOGGED_IN_USER_HEADER = "canvas-logged-in-user-id"

# schema_key of the "Recent Labs" custom command declared in CANVAS_MANIFEST.json.
RECENT_LABS_SCHEMA_KEY = "recentLabsSummary"


def build_fax_note_html(patient_id: str, groups: list) -> str:  # type: ignore[no-untyped-def]
    """Render the fax-ready note body (patient header + grouped lab results) as HTML."""
    patient = Patient.objects.filter(id=patient_id).first()
    patient_name = ""
    patient_dob = ""
    if patient is not None:
        patient_name = f"{patient.first_name} {patient.last_name}".strip()
        patient_dob = patient.birth_date.strftime("%m/%d/%Y") if patient.birth_date else ""

    return render_to_string(
        "templates/fax_summary.html",
        {"patient_name": patient_name, "patient_dob": patient_dob, "groups": groups},
    )


def resolve_note_type_id(configured: str) -> str | None:
    """Resolve a configured note type (a UUID, code, or name) to a note type id.

    Accepts the note type's UUID, its code (e.g. ``faxedlabs``), or its display name
    (e.g. ``Faxed Labs``), so the secret can be set to whichever is convenient. Code is
    tried before name. Returns the id as a string, or None if nothing matches.
    """
    try:
        UUID(str(configured))
    except ValueError:
        pass
    else:
        if NoteType.objects.filter(id=configured).exists():
            return str(configured)

    for field in ("code", "name"):
        nt_id = (
            NoteType.objects.filter(is_active=True, **{field: configured})
            .values_list("id", flat=True)
            .first()
        )
        if nt_id is not None:
            return str(nt_id)
    return None


def first_active_practice_location_id() -> str | None:
    """Return the id of the first active practice location, or None if there isn't one."""
    loc_id = (
        PracticeLocation.objects.filter(active=True).values_list("id", flat=True).first()
    )
    return str(loc_id) if loc_id else None


class CreateFaxSummaryAPI(StaffSessionAuthMixin, SimpleAPIRoute):
    """Creates a visit note summarizing the patient's recent labs, ready to fax."""

    PATH = "/routes/create-fax-summary"

    def post(self) -> list[Response | Effect]:
        """Build the lab-summary note and return its create + HPI effects."""
        configured_note_type = self.secrets.get("RECENT_LABS_NOTE_TYPE_ID")
        if not configured_note_type:
            log.error("CreateFaxSummaryAPI: RECENT_LABS_NOTE_TYPE_ID secret is not set")
            return [
                JSONResponse(
                    {"error": "RECENT_LABS_NOTE_TYPE_ID is not configured.", "success": False}
                )
            ]

        try:
            body = self.request.json()
        except Exception:
            return [JSONResponse({"error": "Invalid JSON in request body.", "success": False})]

        if not isinstance(body, dict):
            return [JSONResponse({"error": "Invalid JSON in request body.", "success": False})]

        patient_id = body.get("patient_id")
        if not patient_id:
            return [JSONResponse({"error": "Patient ID is required.", "success": False})]

        groups = get_recent_results_by_test(patient_id)
        if not groups:
            return [JSONResponse({"error": "No lab results on file to summarize.", "success": False})]

        note_type_id = resolve_note_type_id(configured_note_type)
        if not note_type_id:
            log.error(f"CreateFaxSummaryAPI: note type '{configured_note_type}' not found")
            return [
                JSONResponse(
                    {
                        "error": (
                            f"Configured note type '{configured_note_type}' was not found. "
                            "Set RECENT_LABS_NOTE_TYPE_ID to a valid visit note type name or id."
                        ),
                        "success": False,
                    }
                )
            ]

        provider_id = self.request.headers.get(LOGGED_IN_USER_HEADER)
        if not provider_id:
            log.error("CreateFaxSummaryAPI: no logged-in user id on the request")
            return [JSONResponse({"error": "Could not determine the logged-in provider.", "success": False})]

        location_id = (
            self.secrets.get("RECENT_LABS_PRACTICE_LOCATION_ID")
            or first_active_practice_location_id()
        )
        if not location_id:
            log.error("CreateFaxSummaryAPI: no active practice location available")
            return [JSONResponse({"error": "No active practice location is available for the note.", "success": False})]

        content = build_fax_note_html(patient_id, groups)
        note_id = str(uuid4())

        try:
            note_effect = Note(
                instance_id=note_id,
                note_type_id=note_type_id,
                patient_id=patient_id,
                provider_id=provider_id,
                practice_location_id=location_id,
                datetime_of_service=datetime.now(timezone.utc),
                title="Recent Labs Summary",
            ).create()

            command_effect = CustomCommand(
                note_uuid=note_id,
                schema_key=RECENT_LABS_SCHEMA_KEY,
                content=content,
                print_content=content,
            ).originate()
        except ValidationError as e:  # expected: bad note-type config / patient validation
            log.error(f"CreateFaxSummaryAPI: failed to build note effects: {e}", exc_info=True)
            return [JSONResponse({"error": "Could not create summary note.", "success": False})]

        log.info(f"CreateFaxSummaryAPI: created summary note {note_id} for patient {patient_id}")
        return [
            JSONResponse(
                {
                    "success": True,
                    "note_id": note_id,
                    "message": "Lab summary note created.",
                }
            ),
            note_effect,
            command_effect,
        ]
