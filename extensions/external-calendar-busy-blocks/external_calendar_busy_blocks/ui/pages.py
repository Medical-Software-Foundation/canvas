from http import HTTPStatus

from canvas_sdk.effects.simple_api import HTMLResponse, PlainTextResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string

from external_calendar_busy_blocks.auth import canonical_staff_id
from external_calendar_busy_blocks.data.models import StaffCalendarFeed


class ConfigPage(StaffSessionAuthMixin, SimpleAPI):
    """GET /pages/config — renders the connect/disconnect HTML page."""

    @api.get("/pages/config")
    def render(self) -> list[Response]:
        staff_id = canonical_staff_id(self.request.headers)
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
        # render_to_string is typed `str | None`. The current SDK raises
        # FileNotFoundError on a missing template rather than returning None,
        # but guard against the declared contract so a None can never reach
        # HTMLResponse (whose content.encode() would raise) — return an
        # explicit 500 instead.
        if html is None:
            return [PlainTextResponse(
                "Unable to render the configuration page.",
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )]
        return [HTMLResponse(html, status_code=HTTPStatus.OK)]
