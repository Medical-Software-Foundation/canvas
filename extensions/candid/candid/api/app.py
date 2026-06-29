"""SimpleAPI that serves the static assets for the Candid applications.

The dashboard and claim-timeline apps are launched as iframed pages
(``LaunchModalEffect(url=...)``). This handler serves their HTML, CSS, and JS
from ``static/`` so each lives in its own file rather than embedded in Python.

Routes (under ``/plugin-io/api/candid/app``):

- ``/dashboard`` + ``/dashboard.css`` + ``/dashboard.js``
- ``/claim-timeline`` + ``/claim-timeline.css`` + ``/claim-timeline.js``

The claim-timeline page takes a ``claim_id`` query param, rendered into the
page as a ``data-claim-id`` attribute the JS reads on load.
"""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string


def _asset(template_name: str, content_type: str) -> Response:
    """Serve a static file from the plugin's ``static/`` directory."""
    return Response(
        (render_to_string(template_name) or "").encode(),
        content_type=content_type,
    )


class CandidAppAssets(StaffSessionAuthMixin, SimpleAPI):
    """Serve HTML/CSS/JS for the Candid dashboard and claim-timeline apps."""

    PREFIX = "/app"

    @api.get("/dashboard")
    def dashboard(self) -> list[Response | Effect]:
        return [HTMLResponse(render_to_string("static/dashboard.html") or "")]

    @api.get("/dashboard.css")
    def dashboard_css(self) -> list[Response | Effect]:
        return [_asset("static/dashboard.css", "text/css")]

    @api.get("/dashboard.js")
    def dashboard_js(self) -> list[Response | Effect]:
        return [_asset("static/dashboard.js", "text/javascript")]

    @api.get("/claim-timeline")
    def claim_timeline(self) -> list[Response | Effect]:
        claim_id = self.request.query_params.get("claim_id")
        return [
            HTMLResponse(
                render_to_string("static/claim-timeline.html", {"claim_id": claim_id})
                or ""
            )
        ]

    @api.get("/claim-timeline.css")
    def claim_timeline_css(self) -> list[Response | Effect]:
        return [_asset("static/claim-timeline.css", "text/css")]

    @api.get("/claim-timeline.js")
    def claim_timeline_js(self) -> list[Response | Effect]:
        return [_asset("static/claim-timeline.js", "text/javascript")]
