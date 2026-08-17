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
                # Wiring only, nothing identifiable: the roster fetches its rows
                # over the authenticated API rather than having them baked into a
                # document that may be cached or copied out of the browser. The
                # patient key narrows the list when a chart sent the reader here;
                # the names behind it still arrive over the API.
                "config_json": safe_json(
                    {
                        "apiBase": API_BASE,
                        "cacheBust": CACHE_BUST,
                        "focusPatientId": self._add_for_patient_id(),
                    }
                ),
            },
        )
        # no-cache like the assets below. The page carries the cache-bust token
        # for roster.css/js, but nothing was busting the document that holds
        # them -- so a redeploy could leave a browser rendering the previous
        # shell against the new API.
        return [
            HTMLResponse(
                html,
                status_code=HTTPStatus.OK,
                headers={"Cache-Control": "no-cache"},
            )
        ]

    @api.get("/add")
    def get_add_form(self) -> list[Response | Effect]:
        """The compact add form the chart button opens.

        A page of its own rather than the roster with a parameter, because a
        dialog and a full-width table want different sizes from the host modal.
        It reads nothing itself: the patient's name and the dropdown choices are
        fetched over the authenticated API, so this document holds only wiring.
        """
        html = render_to_string(
            "templates/add_patient.html",
            {
                "config_json": safe_json(
                    {
                        "apiBase": API_BASE,
                        "cacheBust": CACHE_BUST,
                        "patientId": self._add_for_patient_id(),
                    }
                ),
            },
        )
        return [
            HTMLResponse(
                html,
                status_code=HTTPStatus.OK,
                headers={"Cache-Control": "no-cache"},
            )
        ]

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
