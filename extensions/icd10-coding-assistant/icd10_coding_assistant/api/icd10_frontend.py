"""SimpleAPI endpoint that serves the interactive ICD-10 coding frontend.

Only index.html goes through the Django template engine (to inject patient_id
and host). styles.css and script.js are returned as raw strings — they contain
no template syntax and running them through the engine is unnecessary overhead.
"""

from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from logger import log


class ICD10FrontendAPI(StaffSessionAuthMixin, SimpleAPI):
    """Serve the interactive HTML/JS/CSS UI for ICD-10 coding.

    Authentication: StaffSessionAuthMixin validates the Canvas session cookie
    so only logged-in staff can load the UI (already guaranteed by the chart
    context, but still enforced here for defense in depth).
    """

    PREFIX = "/ui"

    @api.get("/icd10-coding")
    def get(self) -> list[Response | Effect]:
        """Serve the interactive HTML page."""
        patient_id: str = self.request.query_params.get("patient_id", "")
        if not patient_id:
            log.error("[ICD-10 Coding] Frontend accessed without patient_id parameter")
            return [
                HTMLResponse(
                    "<html><body><h1>Error</h1><p>No patient ID provided</p></body></html>",
                    status_code=400,
                )
            ]

        host: str = self.request.headers.get("host", "")
        log.info(
            f"[ICD-10 Coding] Serving frontend for patient {patient_id} from host {host}"
        )

        html = render_to_string(
            "templates/index.html",
            {
                "patient_id": patient_id,
                "host": host,
            },
        )
        return [HTMLResponse(html, status_code=HTTPStatus.OK)]

    @api.get("/styles.css")
    def get_css(self) -> list[Response | Effect]:
        """Serve the stylesheet. No template interpolation needed."""
        # render_to_string with no context variables is effectively a raw file read.
        # We call it inside the method (not at module level) so it works in the
        # plugin sandbox but also does not break test collection.
        return [
            Response(
                render_to_string("templates/styles.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
            )
        ]

    @api.get("/script.js")
    def get_script(self) -> list[Response | Effect]:
        """Serve the JavaScript. No template interpolation needed."""
        return [
            Response(
                render_to_string("templates/script.js").encode(),
                status_code=HTTPStatus.OK,
                content_type="application/javascript",
            )
        ]
