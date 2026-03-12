from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, Response
from canvas_sdk.handlers.simple_api import SessionCredentials, SimpleAPI, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.note import NoteStates
from canvas_sdk.v1.data.staff import Staff


class PrescriptionProcessingWebApp(SimpleAPI):
    """Web handler for the Prescription Processing Dashboard."""

    PREFIX = "/app"

    def authenticate(self, credentials: SessionCredentials) -> bool:
        """Authenticate using session credentials."""
        return credentials.logged_in_user is not None

    @api.get("/dashboard")
    def index(self) -> list[Response | Effect]:
        """Serve the main dashboard page."""
        logged_in_user = Staff.objects.get(id=self.request.headers["canvas-logged-in-user-id"])

        # Get prescriber filter from query params
        selected_prescriber = self.request.query_params.get("prescriber")

        # Editable note states
        editable_states = [
            NoteStates.NEW,
            NoteStates.CONVERTED,
            NoteStates.PUSHED,
            NoteStates.UNLOCKED,
            NoteStates.RESTORED,
            NoteStates.UNDELETED,
        ]

        # Query prescribe commands that are not committed and not entered in error,
        # have all required fields filled in, and are in editable notes
        pending_prescriptions = Command.objects.filter(
            schema_key="prescribe",
            committer__isnull=True,
            entered_in_error__isnull=True,
            data__prescribe__isnull=False,
            data__prescriber__isnull=False,
            data__pharmacy__isnull=False,
            data__days_supply__isnull=False,
            note__current_state__state__in=editable_states,
        ).exclude(
            data__sig="",
        ).select_related("patient", "note", "originator__staff")

        # Get unique prescribers for filter dropdown
        prescribers = set()
        for prescription in pending_prescriptions:
            prescriber = prescription.data.get("prescriber")
            if prescriber and prescriber.get("text"):
                prescribers.add((str(prescriber["value"]), prescriber["text"]))
        prescribers = sorted(prescribers, key=lambda x: x[1])

        # Apply prescriber filter if selected
        if selected_prescriber:
            pending_prescriptions = pending_prescriptions.filter(
                data__prescriber__value=int(selected_prescriber)
            )
            selected_prescriber = str(selected_prescriber)

        context = {
            "first_name": logged_in_user.first_name,
            "last_name": logged_in_user.last_name,
            "pending_prescriptions": pending_prescriptions,
            "prescribers": prescribers,
            "selected_prescriber": selected_prescriber,
        }

        return [
            HTMLResponse(
                render_to_string("static/index.html", context),
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/main.js")
    def get_main_js(self) -> list[Response | Effect]:
        """Serve the main JavaScript file."""
        return [
            Response(
                render_to_string("static/main.js").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/javascript",
            )
        ]

    @api.get("/styles.css")
    def get_css(self) -> list[Response | Effect]:
        """Serve the CSS styles file."""
        return [
            Response(
                render_to_string("static/styles.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
            )
        ]
