"""Serves the staff-facing pages and their static assets.

Split from the data API so the manifest can declare honest data access: this
class reads nothing at all, it only renders files. It also does not look the
patient up -- the picker page passes the key straight through to its front end,
which resolves it against the data API.
"""

from http import HTTPStatus
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string

from patient_resources import CACHE_BUST
from patient_resources.constants import API_BASE, STAFF_ASSET_BASE
from patient_resources.services.html import safe_json

_NO_CACHE = {"Cache-Control": "no-cache"}


class StaffPagesAPI(StaffSessionAuthMixin, SimpleAPI):
    """The library page, the picker page, and the assets they load."""

    PREFIX = "/app"

    def _param(self, name: str) -> str:
        params = getattr(self.request, "query_params", None) or {}
        return str(params.get(name, "") or "").strip()

    def _page(self, template: str, config: dict[str, Any]) -> list[Response | Effect]:
        html = render_to_string(
            template,
            {
                "asset_base": STAFF_ASSET_BASE,
                "cache_bust": CACHE_BUST,
                "config_json": safe_json(config),
            },
        )
        return [HTMLResponse(html, status_code=HTTPStatus.OK, headers=dict(_NO_CACHE))]

    @api.get("/")
    def get_library_page(self) -> list[Response | Effect]:
        """The admin library."""
        return self._page("templates/library.html", {"apiBase": API_BASE, "cacheBust": CACHE_BUST})

    @api.get("/picker")
    def get_picker_page(self) -> list[Response | Effect]:
        """The chart picker.

        The patient key is echoed into the page config, not resolved here. An
        empty value renders a page that reports the patient could not be found
        rather than one that silently shares with nobody.
        """
        return self._page(
            "templates/picker.html",
            {
                "apiBase": API_BASE,
                "cacheBust": CACHE_BUST,
                "patientId": self._param("patient"),
            },
        )

    @api.get("/library.css")
    def get_library_css(self) -> list[Response | Effect]:
        return _asset("static/css/library.css", "text/css")

    @api.get("/library.js")
    def get_library_js(self) -> list[Response | Effect]:
        return _asset("static/js/library.js", "application/javascript")

    @api.get("/picker.js")
    def get_picker_js(self) -> list[Response | Effect]:
        return _asset("static/js/picker.js", "application/javascript")


def _asset(path: str, content_type: str) -> list[Response | Effect]:
    """Serve one text asset from the plugin package.

    ``render_to_string`` is the only file access the sandbox allows -- there is no
    filesystem, no ``open()`` -- and it returns ``str``, which is why every asset
    this plugin ships is text.
    """
    body = render_to_string(path)
    return [
        Response(
            body.encode(),
            status_code=HTTPStatus.OK,
            content_type=content_type,
            headers=dict(_NO_CACHE),
        )
    ]
