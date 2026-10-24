"""SimpleAPI - Configuration persistence endpoints for visit-summaries."""
from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string

from visit_summaries.helpers.config_store import get_config, update_config
from visit_summaries.helpers.styles import SHARED_CSS


class ConfigApi(StaffSessionAuthMixin, SimpleAPI):
    """HTTP endpoints for reading and writing visit-summary configuration."""

    @api.get("/config")
    def get_config(self) -> list[Response | Effect]:
        """Return the current configuration as JSON."""
        return [JSONResponse(get_config(), status_code=HTTPStatus.OK)]

    @api.post("/config")
    def save_config(self) -> list[Response | Effect]:
        """Accept a JSON body and update the configuration store."""
        body = self.request.json()
        if not isinstance(body, dict):
            return [
                JSONResponse(
                    {"error": "Expected a JSON object"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        # Only accept known keys
        allowed_keys = {
            "enable_previous_visit",
            "enable_since_last_visit",
            "enable_avs",
        }
        sanitized = {k: v for k, v in body.items() if k in allowed_keys}
        updated = update_config(sanitized)
        return [JSONResponse(updated, status_code=HTTPStatus.OK)]

    @api.get("/config-panel")
    def config_panel(self) -> list[Response | Effect]:
        """Render the configuration panel HTML."""
        config = get_config()
        save_url = self.request.query_params.get("save_url", "/plugin-io/api/visit_summaries/config")
        # Ensure save_url is a relative path to prevent XSS via javascript: or data: URLs
        if not save_url.startswith("/"):
            save_url = "/plugin-io/api/visit_summaries/config"
        content = render_to_string(
            "templates/config_panel.html",
            {
                "config": config,
                "save_url": save_url,
                "shared_css": SHARED_CSS,
            },
        )
        return [HTMLResponse(content, status_code=HTTPStatus.OK)]
