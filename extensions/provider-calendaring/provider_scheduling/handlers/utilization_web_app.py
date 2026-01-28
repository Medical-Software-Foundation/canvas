from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.staff import Staff, StaffRole


class UtilizationWebApp(StaffSessionAuthMixin, SimpleAPI):
    """A web application for displaying schedule utilization metrics."""

    PREFIX = "/app"

    @api.get("/utilization-dashboard")
    def index(self) -> list[Response | Effect]:
        """Serve the main HTML page with context data."""
        logged_in_user_id = self.request.headers.get("canvas-logged-in-user-id")

        providers = Staff.objects.filter(
            active=True,
            roles__domain__in=StaffRole.RoleDomain.clinical_domains(),
        ).distinct()

        context = {
            "providers": [
                {
                    "id": provider.id,
                    "name": provider.credentialed_name,
                    "full_name": provider.full_name,
                }
                for provider in providers
            ],
            "loggedInUserId": logged_in_user_id,
        }

        return [
            HTMLResponse(
                render_to_string("static/utilization/index.html", context),
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/utilization.js")
    def get_main_js(self) -> list[Response | Effect]:
        """Serve the main JavaScript file."""
        return [
            Response(
                render_to_string("static/utilization/main.js").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/javascript",
            )
        ]

    @api.get("/utilization.css")
    def get_css(self) -> list[Response | Effect]:
        """Serve the main CSS file."""
        return [
            Response(
                render_to_string("static/utilization/styles.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
            )
        ]
