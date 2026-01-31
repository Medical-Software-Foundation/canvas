"""
SimpleAPI and WebSocket handlers for high-risk medications.

Provides endpoints for fetching HTML and listening for real-time updates.
"""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.handlers.simple_api.websocket import WebSocketAPI
from canvas_sdk.templates import render_to_string
from http import HTTPStatus

from high_risk_medications.helper import get_high_risk_meds

from logger import log


class HighRiskMedsAPI(StaffSessionAuthMixin, SimpleAPI):
    """SimpleAPI handler for high-risk medications view."""


    @api.get("/high-risk-meds/<patient_id>")
    def get_view(self) -> list[Response | Effect]:
        """Render the high-risk medications HTML for the given patient."""
        patient_id = self.request.path_params["patient_id"]

        log.info(f"Loading high-risk medications view for patient {patient_id}")

        try:
            high_risk_meds = get_high_risk_meds(patient_id, self.secrets["HIGH_RISK_PATTERNS"])

            context = {
                "patient_id": patient_id,
                "medications": high_risk_meds,
                "customer_identifier": self.environment['CUSTOMER_IDENTIFIER'],
            }

            return [
                HTMLResponse(
                    render_to_string("assets/templates/high_risk_meds_view.html", context),
                    status_code=HTTPStatus.OK,
                )
            ]

        except (KeyError, AttributeError) as e:
            log.error(f"Data access error: {str(e)}")
            return [
                HTMLResponse(
                    render_to_string(
                        "assets/templates/error.html",
                        {"error_message": "Error accessing medication data"}
                    ),
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

    @api.get("/style.css")
    def get_css(self) -> list[Response | Effect]:
        """Serve the stylesheet."""
        return [
            Response(
                render_to_string("assets/templates/style.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
            )
        ]

    @api.get("/script.js")
    def get_script(self) -> list[Response | Effect]:
        """Serve the JavaScript helpers."""
        return [
            Response(
                render_to_string("assets/templates/script.js").encode(),
                status_code=HTTPStatus.OK,
                content_type="application/javascript",
            )
        ]


class HighRiskMedsWebSocket(WebSocketAPI):
    """Authenticate websocket connections for live medication updates."""

    def authenticate(self) -> bool:
        logged_in_user = self.websocket.logged_in_user

        if not logged_in_user:
            return False

        return logged_in_user.get("type") == "Staff"
