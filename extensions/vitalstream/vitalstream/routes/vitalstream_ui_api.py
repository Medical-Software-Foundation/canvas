from http import HTTPStatus

import arrow

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.effects import Effect
from canvas_sdk.effects.observation import CodingData, Observation, ObservationComponentData
from canvas_sdk.effects.simple_api import HTMLResponse, Response
from canvas_sdk.handlers.simple_api import StaffSessionAuthMixin, SimpleAPI, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.note import Note
from canvas_sdk.v1.data.staff import Staff

from vitalstream.util import session_key


# LOINC codes for averaged vital signs
VITAL_SIGNS = {
    "hr": {"code": "103205-1", "display": "Mean heart rate", "units": "{beats}/min"},
    "resp": {"code": "103217-6", "display": "Mean respiratory rate", "units": "/min"},
    "spo2": {"code": "103209-3", "display": "Mean oxygen saturation", "units": "%"},
}

# Blood pressure panel with components
BP_PANEL = {
    "code": "96607-7",
    "display": "Blood pressure panel mean systolic and mean diastolic",
}
BP_COMPONENTS = {
    "sys": {"code": "96608-5", "display": "Systolic blood pressure mean", "units": "mm[Hg]"},
    "dia": {"code": "96609-3", "display": "Diastolic blood pressure mean", "units": "mm[Hg]"},
}


class VitalstreamUIAPI(StaffSessionAuthMixin, SimpleAPI):
    """
    API to serve the VitalStream integration UI.
    """

    def validate_session(self, session_id: str) -> dict | None:
        """
        Validate that the session exists and belongs to the logged-in staff.
        Returns the session dict if valid, None otherwise.
        """
        logged_in_staff = Staff.objects.get(id=self.request.headers["canvas-logged-in-user-id"])
        cache = get_cache()
        session = cache.get(session_key(session_id))

        if session is None or session.get('staff_id') != logged_in_staff.id:
            return None
        return session

    @api.get("/vitalstream-ui/sessions/<session_id>/")
    def index(self) -> list[Response | Effect]:
        """Render the custom UI for the chart application."""
        session_id = self.request.path_params["session_id"]
        session = self.validate_session(session_id)

        if session is None:
            return [
                HTMLResponse(
                    render_to_string("templates/session-not-found.html"),
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        context = {
            "session_id": session_id,
            "subdomain": self.environment["CUSTOMER_IDENTIFIER"],
        }
        return [
            HTMLResponse(
                render_to_string("templates/vitalstream-ui.html", context),
                status_code=HTTPStatus.OK,
            )
        ]

    @api.post("/vitalstream-ui/sessions/<session_id>/measurements/")
    def post_measurements(self) -> list[Response | Effect]:
        """Receive averaged measurements from the UI."""
        session_id = self.request.path_params["session_id"]
        session = self.validate_session(session_id)

        if session is None:
            return [
                Response(
                    b'{"error": "Session not found"}',
                    status_code=HTTPStatus.NOT_FOUND,
                    content_type="application/json",
                )
            ]

        data = self.request.json()
        # data expected: { timestamp, hr, sys, dia, resp, spo2 }

        note = Note.objects.get(dbid=session["note_id"])
        patient_id = note.patient.id
        effective_datetime = arrow.get(data["timestamp"]).datetime

        effects: list[Response | Effect] = []

        # Create individual observations for non-BP vitals
        for key, vital_info in VITAL_SIGNS.items():
            value = data.get(key)
            if value is not None:
                observation = Observation(
                    patient_id=patient_id,
                    note_id=note.dbid,
                    category="vital-signs",
                    name=vital_info["display"],
                    value=str(value),
                    units=vital_info["units"],
                    effective_datetime=effective_datetime,
                    codings=[CodingData(
                        system="http://loinc.org",
                        code=vital_info["code"],
                        display=vital_info["display"],
                    )],
                )
                effects.append(observation.create())

        # Create blood pressure panel if either sys or dia is present
        sys_value = data.get("sys")
        dia_value = data.get("dia")
        if sys_value is not None or dia_value is not None:
            components = []
            for key, component_info in BP_COMPONENTS.items():
                value = data.get(key)
                if value is not None:
                    components.append(ObservationComponentData(
                        name=component_info["display"],
                        value_quantity=str(value),
                        value_quantity_unit=component_info["units"],
                        codings=[CodingData(
                            system="http://loinc.org",
                            code=component_info["code"],
                            display=component_info["display"],
                        )],
                    ))

            bp_observation = Observation(
                patient_id=patient_id,
                note_id=note.dbid,
                category="vital-signs",
                name=BP_PANEL["display"],
                effective_datetime=effective_datetime,
                codings=[CodingData(
                    system="http://loinc.org",
                    code=BP_PANEL["code"],
                    display=BP_PANEL["display"],
                )],
                components=components,
            )
            effects.append(bp_observation.create())

        effects.append(
            Response(
                b'{"status": "ok"}',
                status_code=HTTPStatus.OK,
                content_type="application/json",
            )
        )

        return effects

    # Serve the application js
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

    # Serve the application styles
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
