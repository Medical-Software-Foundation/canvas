"""SimpleAPI endpoints for the preventive screenings admin page.

Serves the screening editor, the stored rules and the catalog it picks from,
plus the endpoint it saves back to.

Access is gated by the ADMIN_STAFF_KEYS plugin variable (a comma-separated list
of staff keys), which is NOT editable from the page itself. It fails closed:
with the variable unset, nobody gets in. There is deliberately no hardcoded
bypass - the variable is set outside this page (plugin settings or
`canvas config set`), so the page can never lock the last admin out, and every
admin is visible in one place the practice controls. The app-drawer icon stays
visible to everyone - the SDK has no per-staff icon control - so access is
enforced here, on open.
"""

from http import HTTPStatus
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, api
from canvas_sdk.handlers.simple_api.security import StaffSessionAuthMixin
from logger import log

from preventive_screenings.api.admin_page import ACCESS_DENIED_HTML, build_admin_html
from preventive_screenings.services.catalog import catalog_for_ui
from preventive_screenings.services.config_store import MAX_SCREENINGS, load_config, save_config
from preventive_screenings.services.order_catalog import order_code_warnings


class ScreeningAdminAPI(StaffSessionAuthMixin, SimpleAPI):
    """Endpoints backing the screening editor."""

    PREFIX = ""

    def _staff_id(self) -> str:
        return str(self.request.headers.get("canvas-logged-in-user-id", ""))

    def _admin_allowed(self) -> bool:
        """Whether the logged-in staff member may view or change the screenings."""
        staff_id = self._staff_id()
        raw = (self.secrets.get("ADMIN_STAFF_KEYS") or "").strip()
        if not raw:
            log.warning("ADMIN_STAFF_KEYS not configured, denying Preventive Screenings access")
            return False
        allowed = {key.strip() for key in raw.split(",") if key.strip()}
        if staff_id and staff_id in allowed:
            return True
        log.warning(f"Preventive Screenings access denied for staff key '{staff_id}'")
        return False

    def _parse_body(self) -> dict[str, Any]:
        """Parse the request body as a JSON object; anything else reads as empty.

        ``ValueError`` covers every way the SDK's ``json()`` fails on a bad body:
        base64, UTF-8 and JSON decoding errors all subclass it.
        """
        try:
            parsed = self.request.json()
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @api.get("/admin/ui")
    def serve_admin(self) -> list[Response | Effect]:
        """Return the screening editor, or an access-denied page."""
        if not self._admin_allowed():
            return [HTMLResponse(ACCESS_DENIED_HTML, status_code=HTTPStatus.FORBIDDEN)]
        return [HTMLResponse(build_admin_html())]

    @api.get("/admin/config")
    def get_config(self) -> list[Response | Effect]:
        """Return the current screenings and the catalog the editor picks from."""
        if not self._admin_allowed():
            return [JSONResponse({"error": "forbidden"}, status_code=HTTPStatus.FORBIDDEN)]
        config = load_config()
        return [
            JSONResponse(
                {
                    "config": config,
                    "catalog": catalog_for_ui(),
                    # Which configured order codes this practice's own catalogs do
                    # not carry. An unresolvable code stages an order with every
                    # field empty, and it does so silently - the failure that cost
                    # five deploys before anyone thought to check the code system.
                    "unresolvable_order_codes": order_code_warnings(config),
                }
            )
        ]

    @api.post("/admin/config")
    def put_config(self) -> list[Response | Effect]:
        """Persist the screenings edited in the form."""
        if not self._admin_allowed():
            return [
                JSONResponse(
                    {"success": False, "error": "forbidden"}, status_code=HTTPStatus.FORBIDDEN
                )
            ]
        # CSRF defence. The SDK parses a JSON body whatever its declared type, so a
        # cross-site `<form enctype="text/plain">` could otherwise post a forged config
        # with an admin's session. A cross-origin `application/json` request needs a
        # CORS preflight, which a foreign site cannot pass. The editor sends this type.
        if self.request.content_type != "application/json":
            return [
                JSONResponse(
                    {"success": False, "error": "Content-Type must be application/json"},
                    status_code=HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                )
            ]
        config = self._parse_body().get("config")
        if not isinstance(config, dict) or not isinstance(config.get("screenings"), list):
            return [
                JSONResponse(
                    {"success": False, "error": "Invalid configuration"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        if len(config["screenings"]) > MAX_SCREENINGS:
            return [
                JSONResponse(
                    {
                        "success": False,
                        "error": f"At most {MAX_SCREENINGS} screenings can be saved.",
                    },
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        if save_config(config):
            return [JSONResponse({"success": True})]
        return [
            JSONResponse(
                {
                    "success": False,
                    "error": "Could not save - the custom data namespace may not be set up. "
                    "Reinstall the plugin.",
                }
            )
        ]
