from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import Response
from canvas_sdk.handlers.simple_api import Credentials, SimpleAPI, api
from canvas_sdk.templates import render_to_string
from logger import log


class Static(SimpleAPI):
    """
    Serves static files for the intake form.
    """

    PREFIX = "/static"

    def authenticate(self, credentials: Credentials) -> bool:
        """
        Allow unauthenticated access to static files.
        Always returns True to allow public access.
        """
        return True

    @api.get("/css")
    def serve_css(self) -> list[Response | Effect]:
        """
        Serve the intake.css file.

        Endpoint: GET /plugin-io/api/intake_agent/static/css
        """
        log.info("Serving intake.css")

        try:
            # Use render_to_string to read the CSS file (with empty context)
            css_content = render_to_string("static/css/intake.css", {})
            # Response expects bytes, so encode the string
            return [Response(css_content.encode(), content_type="text/css")]
        except Exception as e:
            log.error(f"Error serving CSS: {e}")
            return [Response(b"/* CSS file not found */", content_type="text/css", status_code=404)]

    @api.get("/js")
    def serve_js(self) -> list[Response | Effect]:
        """
        Serve the intake.js file.

        Endpoint: GET /plugin-io/api/intake_agent/static/js
        """
        log.info("Serving intake.js")

        try:
            # Use render_to_string to read the JS file (with empty context)
            js_content = render_to_string("static/js/intake.js", {})
            # Response expects bytes, so encode the string
            return [Response(js_content.encode(), content_type="application/javascript")]
        except Exception as e:
            log.error(f"Error serving JS: {e}")
            return [Response(b"/* JS file not found */", content_type="application/javascript", status_code=404)]
