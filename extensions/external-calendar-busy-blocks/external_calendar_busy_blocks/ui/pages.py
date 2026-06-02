from http import HTTPStatus

from canvas_sdk.effects.simple_api import HTMLResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string

from external_calendar_busy_blocks.data.models import StaffCalendarFeed


class ConfigPage(StaffSessionAuthMixin, SimpleAPI):
    """GET /pages/config — renders the connect/disconnect HTML page."""

    @api.get("/pages/config")
    def render(self) -> list[Response]:
        staff_id = self.request.headers.get("canvas-logged-in-user-id")
        feed = StaffCalendarFeed.objects.filter(staff_id=staff_id).first() if staff_id else None
        html = render_to_string(
            "templates/config.html",
            {
                "feed": feed,
                "connected": feed is not None and feed.is_active,
                "post_url": "/plugin-io/api/external_calendar_busy_blocks/feeds",
                "delete_url": "/plugin-io/api/external_calendar_busy_blocks/feeds/delete",
            },
        )
        return [HTMLResponse(html, status_code=HTTPStatus.OK)]
