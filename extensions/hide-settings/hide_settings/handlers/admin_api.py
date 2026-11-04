import json
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SessionCredentials, SimpleAPI, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.staff import StaffRole
from logger import log

from hide_settings.models.config import SettingsAccessConfig

ADMIN_STAFF_IDS_SECRET = "ADMIN_STAFF_IDS"

# Changes on every plugin load, so browsers fetch fresh CSS/JS after an upgrade.
_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))

DOMAIN_LABELS = {"ADM": "Administrative", "CLI": "Clinical", "HYB": "Hybrid"}


def _canonical_staff_id(value: Any) -> str:
    """Staff ids compare dashless and lowercase, so either UUID form can be configured."""
    return str(value or "").strip().replace("-", "").lower()


def _admin_staff_ids(secrets: dict[str, Any]) -> set[str]:
    raw = secrets.get(ADMIN_STAFF_IDS_SECRET) or ""
    return {_canonical_staff_id(part) for part in raw.split(",") if part.strip()}


def _json_for_script(value: Any) -> str:
    """JSON that is safe to place inside a <script> block."""
    return json.dumps(value).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _known_roles() -> list[dict[str, str]]:
    """One entry per distinct role internal code held by any staff member."""
    seen: set[str] = set()
    roles: list[dict[str, str]] = []
    for role in StaffRole.objects.values("internal_code", "name", "domain", "role_type"):
        code = role["internal_code"]
        if code in seen:
            continue
        seen.add(code)
        roles.append(
            {
                "internal_code": code,
                "name": role["name"],
                "domain": role["domain"],
                "domain_label": DOMAIN_LABELS.get(role["domain"], role["domain"]),
                "role_type": role["role_type"] or "",
            }
        )
    roles.sort(key=lambda r: (r["domain"], r["name"]))
    return roles


class AdminAPI(SimpleAPI):
    """Serves the Settings access configuration page to the staff listed in ADMIN_STAFF_IDS."""

    PREFIX = "/admin"

    def authenticate(self, credentials: SessionCredentials) -> bool:
        """Allow only staff whose id is listed in the ADMIN_STAFF_IDS secret."""
        user = credentials.logged_in_user
        if not user or user.get("type") != "Staff":
            return False

        admin_ids = _admin_staff_ids(self.secrets)
        if not admin_ids:
            log.warning(
                "[hide_settings] %s is not set; denying configuration access.",
                ADMIN_STAFF_IDS_SECRET,
            )
            return False

        return _canonical_staff_id(user.get("id")) in admin_ids

    @api.get("/config")
    def config_page(self) -> list[Response | Effect]:
        """Render the role configuration page."""
        config = SettingsAccessConfig.objects.first()
        allowed_codes = set(config.allowed_role_codes or []) if config else set()

        roles = [
            {**role, "allowed": role["internal_code"] in allowed_codes} for role in _known_roles()
        ]
        context = {"roles_json": _json_for_script(roles), "cache_bust": _CACHE_BUST}
        return [HTMLResponse(render_to_string("templates/admin.html", context))]

    @api.post("/config")
    def save_config(self) -> list[Response | Effect]:
        """Save the list of role internal codes allowed to see Settings."""
        try:
            body = self.request.json()
        except ValueError:
            return [JSONResponse({"error": "Request body must be JSON"}, HTTPStatus.BAD_REQUEST)]

        allowed = body.get("allowed_role_codes") if isinstance(body, dict) else None
        if not isinstance(allowed, list) or not all(isinstance(c, str) for c in allowed):
            return [
                JSONResponse(
                    {"error": "allowed_role_codes must be a list of role codes"},
                    HTTPStatus.BAD_REQUEST,
                )
            ]

        known_codes = {role["internal_code"] for role in _known_roles()}
        unknown = sorted(set(allowed) - known_codes)
        if unknown:
            return [
                JSONResponse(
                    {"error": f"Unknown role codes: {', '.join(unknown)}"},
                    HTTPStatus.BAD_REQUEST,
                )
            ]

        allowed_codes = sorted(set(allowed))
        config = SettingsAccessConfig.objects.first()
        if config:
            config.allowed_role_codes = allowed_codes
            config.save()
        else:
            SettingsAccessConfig.objects.create(allowed_role_codes=allowed_codes)

        return [JSONResponse({"status": "ok", "allowed_role_codes": allowed_codes})]

    @api.get("/styles.css")
    def get_css(self) -> list[Response | Effect]:
        """Serve the configuration page stylesheet."""
        return [
            Response(
                render_to_string("templates/admin.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
            )
        ]

    @api.get("/app.js")
    def get_js(self) -> list[Response | Effect]:
        """Serve the configuration page script."""
        return [
            Response(
                render_to_string("templates/admin.js").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/javascript",
            )
        ]
