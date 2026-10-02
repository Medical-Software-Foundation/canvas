"""SimpleAPI serving the failed-fax dashboard page and its JSON actions.

Every route requires a logged-in staff session (``StaffSessionAuthMixin``) and
then repeats the ``FAX_DASHBOARD_STAFF_IDS`` access check, so a patient-portal
session is rejected by the mixin and an unlisted staff member gets a 403.
"""

from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string

from failed_fax_dashboard.services.access import is_staff_allowed
from failed_fax_dashboard.services.actions import (
    ActionError,
    build_comment,
    build_reassign,
    build_resend,
    dismiss_row,
)
from failed_fax_dashboard.services.dashboard import dashboard_page
from failed_fax_dashboard.services.preferences import TABS, reset_views, save_views
from failed_fax_dashboard.services.tasks import assignee_options

PREFIX = "/app"
ASSET_BASE = "/plugin-io/api/failed_fax_dashboard/app"
PAGE_URL = f"{ASSET_BASE}/index"

# Changes on every module load, so a reinstall makes browsers refetch the assets.
CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))

STAFF_ID_HEADER = "canvas-logged-in-user-id"

NOT_AUTHORIZED_HTML = (
    "<!doctype html><html><body style=\"font-family: sans-serif; padding: 2rem;\">"
    "<h2>Not authorized</h2>"
    "<p>Your account does not have access to the failed fax dashboard.</p>"
    "</body></html>"
)


class FailedFaxDashboardAPI(StaffSessionAuthMixin, SimpleAPI):
    """Dashboard page, static assets, data, and row actions."""

    PREFIX = PREFIX

    def _staff_id(self) -> str:
        """Id of the logged-in staff member, taken from the validated session headers."""
        return self.request.headers.get(STAFF_ID_HEADER) or ""

    def _is_allowed(self) -> bool:
        """Whether the logged-in staff member passes the access-list check."""
        return is_staff_allowed(self.secrets, self._staff_id())

    def _forbidden(self) -> list[Response | Effect]:
        """The 403 JSON response."""
        return [JSONResponse({"error": "Not authorized"}, status_code=HTTPStatus.FORBIDDEN)]

    def _body(self) -> dict[str, Any]:
        """The JSON request body as a dict (empty when the body is not an object)."""
        try:
            body = self.request.json()
        except ValueError as error:
            raise ActionError("Request body must be valid JSON") from error
        return body if isinstance(body, dict) else {}

    @api.get("/index")
    def page(self) -> list[Response | Effect]:
        """Serve the dashboard HTML."""
        if not self._is_allowed():
            return [HTMLResponse(NOT_AUTHORIZED_HTML, status_code=HTTPStatus.FORBIDDEN)]
        html = render_to_string(
            "templates/index.html",
            {"asset_base": ASSET_BASE, "cache_bust": CACHE_BUST},
        )
        return [HTMLResponse(html, status_code=HTTPStatus.OK)]

    @api.get("/styles.css")
    def styles(self) -> list[Response | Effect]:
        """Serve the stylesheet."""
        if not self._is_allowed():
            return self._forbidden()
        css = render_to_string("templates/styles.css")
        return [Response(css.encode("utf-8"), status_code=HTTPStatus.OK, content_type="text/css")]

    @api.get("/app.js")
    def script(self) -> list[Response | Effect]:
        """Serve the JavaScript."""
        if not self._is_allowed():
            return self._forbidden()
        js = render_to_string("templates/app.js")
        return [
            Response(
                js.encode("utf-8"),
                status_code=HTTPStatus.OK,
                content_type="application/javascript",
            )
        ]

    @api.get("/failures")
    def failures(self) -> list[Response | Effect]:
        """One tab at the requested filter, sort, and page, plus both tab totals."""
        if not self._is_allowed():
            return self._forbidden()
        params = self.request.query_params
        tab = params.get("tab")
        data = dashboard_page(
            tab if tab in TABS else "sent", params, self._staff_id(), secrets=dict(self.secrets)
        )
        return [JSONResponse(data)]

    @api.get("/people")
    def people(self) -> list[Response | Effect]:
        """Active staff and teams, for the person filter and the reassign picker."""
        if not self._is_allowed():
            return self._forbidden()
        return [JSONResponse(assignee_options())]

    @api.post("/preferences")
    def preferences(self) -> list[Response | Effect]:
        """Save the logged-in staff member's settings, or clear them with ``{"reset": true}``."""
        if not self._is_allowed():
            return self._forbidden()
        try:
            body = self._body()
        except ActionError as error:
            return [JSONResponse({"error": error.message}, status_code=error.status)]
        if body.get("reset") is True:
            reset_views(self._staff_id())
        elif not save_views(self._staff_id(), body.get("views")):
            return [JSONResponse({"error": "Staff member not found"}, status_code=HTTPStatus.FORBIDDEN)]
        return [JSONResponse({"ok": True})]

    @api.post("/resend")
    def resend(self) -> list[Response | Effect]:
        """Resend a failed note fax to the number and recipient entered in the form."""
        if not self._is_allowed():
            return self._forbidden()
        try:
            effect = build_resend(self._body(), staff_id=self._staff_id())
        except ActionError as error:
            return [JSONResponse({"error": error.message}, status_code=error.status)]
        return [JSONResponse({"ok": True}), effect]

    @api.post("/tasks/reassign")
    def reassign(self) -> list[Response | Effect]:
        """Move a row's task to a person or team, noted as a comment under the clicker's name."""
        if not self._is_allowed():
            return self._forbidden()
        try:
            effects = build_reassign(self._body(), staff_id=self._staff_id())
        except ActionError as error:
            return [JSONResponse({"error": error.message}, status_code=error.status)]
        return [JSONResponse({"ok": True}), *effects]

    @api.post("/tasks/comment")
    def comment(self) -> list[Response | Effect]:
        """Add a comment to a row's task, under the logged-in staff member's name."""
        if not self._is_allowed():
            return self._forbidden()
        try:
            effect = build_comment(self._body(), staff_id=self._staff_id())
        except ActionError as error:
            return [JSONResponse({"error": error.message}, status_code=error.status)]
        return [JSONResponse({"ok": True}), effect]

    @api.post("/dismiss")
    def dismiss(self) -> list[Response | Effect]:
        """Dismiss a row so it no longer appears."""
        if not self._is_allowed():
            return self._forbidden()
        try:
            dismiss_row(self._body(), staff_id=self._staff_id())
        except ActionError as error:
            return [JSONResponse({"error": error.message}, status_code=error.status)]
        return [JSONResponse({"ok": True})]
