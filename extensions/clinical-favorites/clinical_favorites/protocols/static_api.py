"""Static asset routes for the Canvas plugin UI design system."""

from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import Response
from canvas_sdk.handlers.simple_api import SimpleAPIRoute, StaffSessionAuthMixin
from canvas_sdk.templates import render_to_string


class PluginUICSSAPI(StaffSessionAuthMixin, SimpleAPIRoute):
    PATH = "/routes/static/canvas-plugin-ui.css"

    def get(self) -> list[Response | Effect]:
        return [
            Response(
                render_to_string("static/canvas-plugin-ui.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
            )
        ]


class PluginUIJSAPI(StaffSessionAuthMixin, SimpleAPIRoute):
    PATH = "/routes/static/canvas-plugin-ui.js"

    def get(self) -> list[Response | Effect]:
        return [
            Response(
                render_to_string("static/canvas-plugin-ui.js").encode(),
                status_code=HTTPStatus.OK,
                content_type="application/javascript",
            )
        ]


class FavoritesCSSAPI(StaffSessionAuthMixin, SimpleAPIRoute):
    PATH = "/routes/static/favorites.css"

    def get(self) -> list[Response | Effect]:
        return [
            Response(
                render_to_string("static/favorites.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
            )
        ]


class FavoritesJSAPI(StaffSessionAuthMixin, SimpleAPIRoute):
    PATH = "/routes/static/favorites.js"

    def get(self) -> list[Response | Effect]:
        return [
            Response(
                render_to_string("static/favorites.js").encode(),
                status_code=HTTPStatus.OK,
                content_type="application/javascript",
            )
        ]
