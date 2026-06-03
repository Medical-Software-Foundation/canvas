"""Patient Visit Summary: ActionButton + SimpleAPI for the visit summary printout."""

from datetime import datetime, timezone
from hmac import compare_digest
from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.handlers.simple_api import SimpleAPI, SessionCredentials, api, Credentials
from canvas_sdk.handlers.simple_api.exceptions import InvalidCredentialsError
from canvas_sdk.effects.simple_api import HTMLResponse, Response
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.note import Note

from logger import log

from patient_visit_summary.images.images_b64 import LOGO_TOP_LEFT, LOGO_TOP_RIGHT
from patient_visit_summary.services.note_data_extractor import NoteDataExtractor

# Regenerated on every plugin (re)load so served HTML and its asset/modal URLs
# bust any stale browser cache.
_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class PatientVisitSummaryButton(ActionButton):
    """Button in the note header that launches the Patient Visit Summary modal."""

    BUTTON_TITLE = "Patient Visit Summary"
    BUTTON_KEY = "PATIENT_VISIT_SUMMARY"
    BUTTON_LOCATION = ActionButton.ButtonLocation.NOTE_HEADER

    def visible(self) -> bool:
        return True

    def handle(self) -> list[Effect]:
        log.info(f"Patient Visit Summary clicked for patient {self.target}")
        # Resolve the note's external UUID so the dbid never appears in the URL.
        note = Note.objects.filter(dbid=self.event.context["note_id"]).first()
        note_uuid = note.id if note else ""
        return [
            LaunchModalEffect(
                url=(
                    f"/plugin-io/api/patient_visit_summary/"
                    f"?patient_id={self.target}&note_id={note_uuid}&v={_CACHE_BUST}"
                )
            ).apply()
        ]


class PatientVisitSummaryAPI(SimpleAPI):
    """SimpleAPI that renders the Patient Visit Summary HTML."""

    def authenticate(self, credentials: Credentials) -> bool:
        try:
            logged_in_user = SessionCredentials(self.request).logged_in_user
            if logged_in_user["type"] == "Staff":
                return True
        except InvalidCredentialsError:
            pass

        api_key_secret = self.secrets.get("simple-api-key")
        request_auth_key = self.request.headers.get("Authorization")
        if api_key_secret and request_auth_key and compare_digest(
            api_key_secret.encode(), request_auth_key.encode()
        ):
            return True
        return False

    @api.get("/")
    def index(self) -> list[Response | Effect]:
        patient_id = self.request.query_params.get("patient_id")
        note_id = self.request.query_params.get("note_id")
        log.info(f"Fetching patient visit summary for patient {patient_id}, note {note_id}")

        extractor = NoteDataExtractor(patient_id=patient_id, note_id=note_id)
        context = extractor.get_template_context()

        # Add logo images and org info used only by this template
        context["cache_bust"] = _CACHE_BUST
        context["logo_top_left"] = LOGO_TOP_LEFT
        context["logo_top_right"] = LOGO_TOP_RIGHT
        context["organization_info"] = {
            "name": "Example Medical Organization",
            "address1": "1234 Main St.",
            "address2": "Suite #22",
            "city": "Dallas",
            "state_code": "TX",
            "postal_code": "75001",
            "phone": "(214) 555-0923",
            "fax": "(214) 555-2714",
        }

        return [
            HTMLResponse(
                render_to_string("templates/patient_visit_summary.html", context=context),
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/style.css")
    def get_css(self) -> list[Response | Effect]:
        return [
            Response(
                render_to_string("templates/style.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
            )
        ]
