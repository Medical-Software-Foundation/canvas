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
            high_risk_meds = get_high_risk_meds(patient_id)

            # Build medication HTML
            med_items = []
            for med in high_risk_meds:
                med_items.append(f"""
                    <div class="med-item">
                        <div class="med-header">
                            <span class="high-risk-badge">HIGH RISK</span>
                            <span class="med-name">{med['name']}</span>
                        </div>
                    </div>
                """)

            context = {
                "patient_id": patient_id,
                "has_high_risk_meds": len(high_risk_meds) > 0,
                "count": len(high_risk_meds),
                "medications": "\n".join(med_items),
                "customer_identifier": self.environment['CUSTOMER_IDENTIFIER'],
            }

            return [
                HTMLResponse(
                    render_to_string("assets/templates/high_risk_meds_view.html", context),
                    status_code=HTTPStatus.OK,
                )
            ]

        except Exception as e:
            log.error(f"Error loading view: {str(e)}")
            return [
                HTMLResponse(
                    render_to_string(
                        "assets/templates/error.html",
                        {"error_message": str(e)}
                    ),
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
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
        log.info(f"WebSocket authenticate called. Channel: {self.websocket.channel}")
        log.info(f"WebSocket headers: {self.websocket.headers}")

        logged_in_user = self.websocket.logged_in_user
        log.info(f"Logged in user: {logged_in_user}")

        if not logged_in_user:
            log.warning("No logged_in_user found in WebSocket connection")
            return False

        is_staff = logged_in_user.get("type") == "Staff"
        log.info(f"Authentication result: {is_staff}")

        return is_staff
