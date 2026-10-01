"""SimpleAPI serving the failed-fax dashboard page and its JSON actions.

Every route requires a logged-in staff session (``StaffSessionAuthMixin``) and
then repeats the ``FAX_DASHBOARD_STAFF_IDS`` access check, so a patient-portal
session is rejected by the mixin and an unlisted staff member gets a 403.
"""

from __future__ import annotations

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
    build_resend,
    build_task,
    dismiss_row,
    resend_prefill,
    task_options,
)
from failed_fax_dashboard.services.failures import (
    DEFAULT_PAGE_SIZE,
    failed_fax_page,
)

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


def _int_param(raw: str | None, default: int) -> int:
    """Parse a positive integer query parameter, falling back to the default."""
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


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
        """One page of failed faxes from the last 90 days."""
        if not self._is_allowed():
            return self._forbidden()
        params = self.request.query_params
        data = failed_fax_page(
            page=_int_param(params.get("page"), 1),
            page_size=_int_param(params.get("page_size"), DEFAULT_PAGE_SIZE),
        )
        return [JSONResponse(data)]

    @api.get("/resend-prefill")
    def resend_defaults(self) -> list[Response | Effect]:
        """Number and suggested recipient name for the resend form."""
        if not self._is_allowed():
            return self._forbidden()
        try:
            data = resend_prefill(self.request.query_params.get("event_id"))
        except ActionError as error:
            return [JSONResponse({"error": error.message}, status_code=error.status)]
        return [JSONResponse(data)]

    @api.post("/resend")
    def resend(self) -> list[Response | Effect]:
        """Resend a failed note fax to the number and recipient entered in the form."""
        if not self._is_allowed():
            return self._forbidden()
        try:
            effect = build_resend(self._body())
        except ActionError as error:
            return [JSONResponse({"error": error.message}, status_code=error.status)]
        return [JSONResponse({"ok": True}), effect]

    @api.get("/task-options")
    def task_form_options(self) -> list[Response | Effect]:
        """Staff and teams for the follow-up task form."""
        if not self._is_allowed():
            return self._forbidden()
        return [JSONResponse(task_options())]

    @api.post("/task")
    def create_task(self) -> list[Response | Effect]:
        """Create a follow-up task for a failed fax, authored by the staff member clicking."""
        if not self._is_allowed():
            return self._forbidden()
        try:
            effect = build_task(self._body(), author_id=self._staff_id())
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
