from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse
from canvas_sdk.handlers.simple_api import Credentials, SimpleAPIRoute
from canvas_sdk.templates import render_to_string
from logger import log


class IntakeAPI(SimpleAPIRoute):
    """
    Patient intake API handler providing an unauthenticated public-facing
    intake form for prospective new patients.
    """

    PATH = "/intake"

    def authenticate(self, credentials: Credentials) -> bool:
        """
        Allow unauthenticated access to this endpoint.
        Always returns True to allow public access.
        """
        return True

    def get(self) -> list[HTMLResponse | Effect]:
        """
        Serve the patient intake form page.

        Endpoint: GET /plugin-io/api/intake_agent/intake
        """
        log.info("Serving patient intake form")

        # Render the template using Canvas SDK's render_to_string
        # Pass empty context since our template is static HTML
        html_content = render_to_string("templates/intake.html", {})

        return [HTMLResponse(html_content)]
