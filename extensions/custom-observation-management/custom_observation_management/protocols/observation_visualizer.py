"""
Observation Visualizer API

SimpleAPI handler for serving the observation visualizer UI.
Proxies observation requests to the ObservationAPI using the API key from secrets.
"""

import uuid
from datetime import datetime, timezone
from http import HTTPStatus

import requests

from canvas_sdk.commands.commands.custom_command import CustomCommand
from canvas_sdk.effects import Effect
from canvas_sdk.effects.note.note import Note
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.note import NoteType
from canvas_sdk.v1.data.practicelocation import PracticeLocation


class ObservationVisualizerAPI(StaffSessionAuthMixin, SimpleAPI):
    """
    SimpleAPI handler for serving the observation visualizer UI.

    Authentication is handled via StaffSessionAuthMixin which validates
    the staff session when accessed from within the Canvas UI.

    Endpoints:
        GET /visualizer - Main HTML page with patient ID embedded
        GET /visualizer/style.css - Stylesheet
        GET /visualizer/script.js - JavaScript file
        GET /visualizer/observations - Proxy to ObservationAPI with API key auth
    """

    @api.get("/visualizer")
    def index(self) -> list[Response | Effect]:
        """
        Serve the main HTML page for the observation visualizer.

        Query Parameters:
            patient_id: The UUID of the patient whose observations to display.

        Returns:
            200 OK: HTML page with the visualizer UI.
        """
        patient_id = self.request.query_params.get("patient_id", "")
        # Get staff ID from the logged-in user headers
        staff_id = self.event.context.get("headers", {}).get("canvas-logged-in-user-id", "")

        return [
            HTMLResponse(
                render_to_string(
                    "templates/observation_visualizer.html",
                    context={"patient_id": patient_id, "staff_id": staff_id}
                ),
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/visualizer/style.css")
    def get_css(self) -> list[Response | Effect]:
        """
        Serve the CSS stylesheet for the visualizer.

        Returns:
            200 OK: CSS stylesheet content.
        """
        return [
            Response(
                render_to_string("templates/observation_visualizer.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
            )
        ]

    @api.get("/visualizer/script.js")
    def get_js(self) -> list[Response | Effect]:
        """
        Serve the JavaScript file for the visualizer.

        Returns:
            200 OK: JavaScript file content.
        """
        return [
            Response(
                render_to_string("templates/observation_visualizer.js").encode(),
                status_code=HTTPStatus.OK,
                content_type="application/javascript",
            )
        ]

    def _proxy_request(self, endpoint: str, allowed_params: list[str]) -> list[Response | Effect]:
        """
        Proxy a request to the ObservationAPI.

        Args:
            endpoint: The API endpoint path (e.g., "/observations").
            allowed_params: List of query parameter names to forward.

        Returns:
            Proxied response from ObservationAPI.
        """
        base_url = self.request.headers.get("Host", "localhost")
        protocol = "https" if self.request.headers.get("X-Forwarded-Proto") == "https" else "http"
        url = f"{protocol}://{base_url}/plugin-io/api/custom_observation_management{endpoint}"

        params = {}
        for key in allowed_params:
            value = self.request.query_params.get(key)
            if value:
                params[key] = value

        response = requests.get(
            url,
            params=params,
            headers={"Authorization": f"{self.secrets['simpleapi-api-key']}"},
            timeout=30
        )
        return [JSONResponse(
            response.json(),
            status_code=HTTPStatus(response.status_code)
        )]


    @api.get("/visualizer/observations")
    def get_observations(self) -> list[Response | Effect]:
        """
        Proxy observations request to the ObservationAPI with pagination and sorting support.

        Query Parameters:
            patient_id (required): The UUID of the patient.
            name (optional): Filter by observation name (comma-separated for multiple).
            category (optional): Filter by category (comma-separated for multiple).
            effective_datetime_start (optional): Filter by start date (ISO 8601).
            effective_datetime_end (optional): Filter by end date (ISO 8601).
            sort_by (optional): Column to sort by (date, name, value, units, category).
            sort_order (optional): Sort order (asc, desc).
            ungrouped (optional): If "true", return flat list without parent-child grouping.
            page (optional): Page number (default: 1).
            page_size (optional): Items per page (default: 25).

        Returns:
            Proxied response from ObservationAPI with pagination metadata.
        """
        return self._proxy_request("/observations", [
            "patient_id", "name", "category",
            "effective_datetime_start", "effective_datetime_end",
            "sort_by", "sort_order", "ungrouped",
            "page", "page_size"
        ])

    @api.get("/visualizer/observation-filters")
    def get_observation_filters(self) -> list[Response | Effect]:
        """
        Proxy observation filters request to the ObservationAPI.

        Query Parameters:
            patient_id (optional): Filter by patient UUID.

        Returns:
            JSON object with unique observation names and categories.
        """
        return self._proxy_request("/observation-filters", ["patient_id"])

    @api.post("/visualizer/create-chart-review")
    def create_chart_review(self) -> list[Response | Effect]:
        """
        Create a Chart Review Note with an observation summary using Custom Command.

        Request Body (JSON):
            patient_id (required): The UUID of the patient.
            staff_id (required): The UUID of the staff member (provider).
            summary_text (required): The formatted observation summary text.
            comment (optional): Clinical comment to include.

        Returns:
            201 Created: Note created with observation summary command.
            400 Bad Request: If required fields are missing.
        """

        data = self.request.json()

        # Validate required fields
        patient_id = data.get("patient_id")
        staff_id = data.get("staff_id")
        summary_text = data.get("summary_text", "")
        comment = data.get("comment", "")
        chart_review_type = NoteType.objects.filter(name="Chart review", is_active=True).first()

        # Get the first practice location for now
        practice_location = PracticeLocation.objects.first()

        # Pre-assign a UUID for the note so we can reference it in the command
        note_id = uuid.uuid4()

        # Create the Note effect with instance_id to pre-assign the UUID
        note_effect = Note(
            note_type_id=str(chart_review_type.id),
            datetime_of_service=datetime.now(timezone.utc),
            patient_id=patient_id,
            practice_location_id=str(practice_location.id),
            provider_id=staff_id,
            instance_id=note_id,
            title="Observation Summary",
        )

        # Build the command content HTML
        content_parts = []
        if comment:
            content_parts.append(
                f'<div style="margin-bottom: 16px;">'
                f'<strong>Clinical Comment:</strong><br/>{comment}'
                f'</div><hr/>'
            )
        # summary_text is already HTML (table format from frontend)
        content_parts.append(summary_text)
        command_content = "\n".join(content_parts)

        # Create the custom command with the pre-assigned note UUID
        command = CustomCommand(
            note_uuid=str(note_id),
            schema_key="observationSummary",
            content=command_content,
            print_content=command_content,
        )

        # Return both effects - note creation first, then command origination
        return [
            note_effect.create(),
            command.originate(),
            JSONResponse(
                {"message": "Chart Review note created with observation summary"},
                status_code=HTTPStatus.CREATED
            )
        ]

