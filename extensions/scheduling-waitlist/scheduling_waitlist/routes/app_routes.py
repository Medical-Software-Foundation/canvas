"""Serves the roster page shell and its static assets.

Split from the data API so the manifest can declare honest data access: this
class reads nothing, it only renders files.
"""

from __future__ import annotations

from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string

from scheduling_waitlist import CACHE_BUST
from scheduling_waitlist.constants import ADD_FOR_PATIENT_PARAM, API_BASE
from scheduling_waitlist.services.html import safe_json

# Assets are addressed absolutely rather than relatively. A relative "roster.css"
# resolves against whether the page URL happened to end in a slash, which is a
# silent 404 waiting to happen.
ASSET_BASE = f"{API_BASE}/app"


class WaitlistAppAPI(StaffSessionAuthMixin, SimpleAPI):
    """The roster page and the CSS/JS it pulls in."""

    PREFIX = "/app"

    @api.get("/")
    def get_roster_page(self) -> list[Response | Effect]:
        """Render the roster shell. Entries are fetched by the page itself."""
        html = render_to_string(
            "templates/roster.html",
            {
                "asset_base": ASSET_BASE,
                "cache_bust": CACHE_BUST,
                # Wiring only. The one patient-related value is the key the chart
                # button put in this page's own URL, which tells the page whose
                # add dialog to open; the name and date of birth behind it are
                # fetched over the authenticated API rather than baked into a
                # document that may be cached or copied out of the browser.
                "config_json": safe_json(
                    {
                        "apiBase": API_BASE,
                        "cacheBust": CACHE_BUST,
                        "addForPatientId": self._add_for_patient_id(),
                    }
                ),
            },
        )
        return [HTMLResponse(html, status_code=HTTPStatus.OK)]

    def _add_for_patient_id(self) -> str:
        """The patient the chart button asked to add, if any."""
        params = getattr(self.request, "query_params", None) or {}
        return str(params.get(ADD_FOR_PATIENT_PARAM) or "").strip()

    @api.get("/roster.css")
    def get_css(self) -> list[Response | Effect]:
        """Serve the roster stylesheet."""
        css = render_to_string("static/css/roster.css")
        return [
            Response(
                css.encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
                headers={"Cache-Control": "no-cache"},
            )
        ]

    @api.get("/roster.js")
    def get_js(self) -> list[Response | Effect]:
        """Serve the roster script."""
        js = render_to_string("static/js/roster.js")
        return [
            Response(
                js.encode(),
                status_code=HTTPStatus.OK,
                content_type="application/javascript",
                headers={"Cache-Control": "no-cache"},
            )
        ]
