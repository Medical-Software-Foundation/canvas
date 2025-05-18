from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, Response
from canvas_sdk.handlers.simple_api import Credentials, SimpleAPIRoute
from canvas_sdk.templates import render_to_string


class YouCanJustDoThings(SimpleAPIRoute):
    PATH = "/inspo"

    def authenticate(self, credentials: Credentials) -> bool:
        return True

    def get(self) -> list[Response | Effect]:
        return [
            HTMLResponse(
                render_to_string('templates/thinkboi_inspo.html'),
                status_code=HTTPStatus.OK,
            )
        ]
