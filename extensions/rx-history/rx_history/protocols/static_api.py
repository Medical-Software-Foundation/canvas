from http import HTTPStatus

from canvas_sdk.effects.simple_api import Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string


class StaticApi(StaffSessionAuthMixin, SimpleAPI):
    """Serves design system CSS and JS assets for plugin templates."""

    PREFIX = "/static"

    @api.get("/canvas-plugin-ui.css")
    def plugin_ui_css(self) -> list[Response]:
        return [
            Response(
                render_to_string("static/canvas-plugin-ui.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
            )
        ]

    @api.get("/canvas-plugin-ui.js")
    def plugin_ui_js(self) -> list[Response]:
        return [
            Response(
                render_to_string("static/canvas-plugin-ui.js").encode(),
                status_code=HTTPStatus.OK,
                content_type="application/javascript",
            )
        ]
