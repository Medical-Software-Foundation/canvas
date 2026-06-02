from http import HTTPStatus
from pathlib import Path

from django.template.engine import Engine

from canvas_sdk.effects.simple_api import HTMLResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api

from external_calendar_busy_blocks.data.models import StaffCalendarFeed

# Resolve template directory relative to this file's package root.
_PLUGIN_DIR = Path(__file__).resolve().parent.parent


def _render(template_name: str, context: dict) -> str:
    """Render a Django template from the plugin's directory."""
    engine = Engine(dirs=[str(_PLUGIN_DIR)])
    template_path = (_PLUGIN_DIR / template_name).resolve()
    return engine.render_to_string(str(template_path), context=context)


class ConfigPage(StaffSessionAuthMixin, SimpleAPI):
    """GET /pages/config — renders the connect/disconnect HTML page."""

    @api.get("/pages/config")
    def render(self) -> list[Response]:
        staff_id = self.request.headers.get("canvas-logged-in-user-id")
        feed = StaffCalendarFeed.objects.filter(staff_id=staff_id).first() if staff_id else None
        html = _render(
            "templates/config.html",
            {
                "feed": feed,
                "connected": feed is not None and feed.is_active,
                "post_url": "/plugin-io/api/external_calendar_busy_blocks/feeds",
                "delete_url": "/plugin-io/api/external_calendar_busy_blocks/feeds/delete",
            },
        )
        return [HTMLResponse(html, status_code=HTTPStatus.OK)]
