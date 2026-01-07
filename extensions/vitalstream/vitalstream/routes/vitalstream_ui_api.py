from http import HTTPStatus

import arrow

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, Response
from canvas_sdk.handlers.simple_api import StaffSessionAuthMixin, SimpleAPI, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.staff import Staff

from vitalstream.util import session_key


class VitalstreamUIAPI(StaffSessionAuthMixin, SimpleAPI):
    """
    API to serve the VitalStream integration UI.
    """

    """
    GET /plugin-io/api/vitalstream/vitalstream-ui/sessions/{session_id}/
    """
    @api.get("/vitalstream-ui/sessions/<session_id>/")
    def index(self) -> list[Response | Effect]:
        """Render the custom UI for the chart application."""
        # Ensure the session exists, and the logged in staff is the one that initiated the session
        logged_in_staff = Staff.objects.get(id=self.request.headers["canvas-logged-in-user-id"])
        
        session_id = self.request.path_params["session_id"]

        cache = get_cache()
        session = cache.get(session_key(session_id))

        if session is None or session.get('staff_id') != logged_in_staff.id:
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
