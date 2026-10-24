"""Serves the patient-facing page and its assets.

A separate class from the staff pages because the auth mixin is a class-level
property: this one must admit patients and refuse staff. Declares no data access.
"""

from http import HTTPStatus
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, Response
from canvas_sdk.handlers.simple_api import PatientSessionAuthMixin, SimpleAPI, api
from canvas_sdk.templates import render_to_string

from patient_resources import CACHE_BUST
from patient_resources.constants import API_BASE, PORTAL_ASSET_BASE
from patient_resources.services.html import safe_json

_NO_CACHE = {"Cache-Control": "no-cache"}


class PortalPagesAPI(PatientSessionAuthMixin, SimpleAPI):
    """The "My Resources" page and the assets it loads."""

    PREFIX = "/portal"

    @api.get("/")
    def get_portal_page(self) -> list[Response | Effect]:
        """The patient's resource list.

        The config block carries no patient identifier. The page has nothing to
        send that could name a patient, and the data route it calls takes no
        parameters -- which is what makes a cross-patient read structurally
        impossible rather than merely checked for.
        """
        config: dict[str, Any] = {"apiBase": API_BASE, "cacheBust": CACHE_BUST}
        html = render_to_string(
            "templates/portal.html",
            {
                "asset_base": PORTAL_ASSET_BASE,
                "cache_bust": CACHE_BUST,
                "config_json": safe_json(config),
            },
        )
        return [HTMLResponse(html, status_code=HTTPStatus.OK, headers=dict(_NO_CACHE))]

    @api.get("/portal.css")
    def get_portal_css(self) -> list[Response | Effect]:
        return _asset("static/css/portal.css", "text/css")

    @api.get("/portal.js")
    def get_portal_js(self) -> list[Response | Effect]:
        return _asset("static/js/portal.js", "application/javascript")


def _asset(path: str, content_type: str) -> list[Response | Effect]:
    body = render_to_string(path)
    return [
        Response(
            body.encode(),
            status_code=HTTPStatus.OK,
            content_type=content_type,
            headers=dict(_NO_CACHE),
        )
    ]
