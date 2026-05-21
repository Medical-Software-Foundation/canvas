"""API endpoints serving the admin UI for the Application iframe."""

from __future__ import annotations

from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string

from provider_availability.engine.storage import get_allowed_staff
from provider_availability.templates.admin_ui import render_admin_page

ACCESS_DENIED_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Access Denied</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600&display=swap" rel="stylesheet">
<style>
body { font-family: 'DM Sans', sans-serif; display: flex; align-items: center;
  justify-content: center; min-height: 100vh; margin: 0; background: #EFF5F7; color: #2c4155; }
.card { background: #fff; border-radius: 14px; padding: 48px; text-align: center;
  box-shadow: 0 4px 16px rgba(13,32,60,0.10); max-width: 420px; }
h1 { font-size: 22px; color: #c0392b; margin-bottom: 8px; }
p { font-size: 15px; color: #5e7a8a; }
</style>
</head>
<body>
<div class="card">
  <h1>Access Denied</h1>
  <p>You are not authorized to access the Provider Availability admin panel.
  Contact your administrator to request access.</p>
</div>
</body>
</html>"""


class UIApi(StaffSessionAuthMixin, SimpleAPI):
    """Serves the admin UI HTML for the provider availability app."""

    PREFIX = "/app"

    @api.get("/availability-admin")
    def get_admin_ui(self) -> list[Response | Effect]:
        """Serve the main admin UI page."""
        allowed = get_allowed_staff()
        if allowed:
            staff_id = getattr(self.request, "staff_id", None) or ""
            if not staff_id or str(staff_id) not in allowed:
                return [HTMLResponse(ACCESS_DENIED_HTML, status_code=HTTPStatus.FORBIDDEN)]
        html = render_admin_page()
        return [HTMLResponse(html, status_code=HTTPStatus.OK)]

    @api.get("/admin.css")
    def get_admin_css(self) -> list[Response | Effect]:
        """Serve the admin UI stylesheet."""
        return [
            Response(
                render_to_string("static/css/admin.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
                headers={"Cache-Control": "no-cache"},
            )
        ]

    @api.get("/admin.js")
    def get_admin_js(self) -> list[Response | Effect]:
        """Serve the admin UI JavaScript."""
        return [
            Response(
                render_to_string("static/js/admin.js").encode(),
                status_code=HTTPStatus.OK,
                content_type="application/javascript",
                headers={"Cache-Control": "no-cache"},
            )
        ]

    @api.get("/tokens.css")
    def get_tokens_css(self) -> list[Response | Effect]:
        """Serve the Canvas design system tokens."""
        return [
            Response(
                render_to_string("static/tokens.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
            )
        ]

    @api.get("/typography.css")
    def get_typography_css(self) -> list[Response | Effect]:
        """Serve the Canvas design system typography."""
        return [
            Response(
                render_to_string("static/typography.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
            )
        ]

    @api.get("/canvas-components.js")
    def get_canvas_components(self) -> list[Response | Effect]:
        """Serve the Canvas design system web components."""
        return [
            Response(
                render_to_string("static/canvas-components.js").encode(),
                status_code=HTTPStatus.OK,
                content_type="application/javascript",
            )
        ]
