from http import HTTPStatus

import arrow

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import Broadcast, JSONResponse, Response
from canvas_sdk.handlers.simple_api import Credentials, APIKeyAuthMixin, SimpleAPI, api

from vitalstream.util import session_key


class CaretakerPortalAPI(SimpleAPI):
    """
    API for receiving readings from the VitalStream Device by Caretaker Medical.
    """

    def authenticate(self, credentials: Credentials) -> bool:
        # Temporarily allow all requests (until 1/2)
        # Just for development purposes.
        return arrow.utcnow() < arrow.get('2026-01-02')


    """
    The device requires the receiving endpoint URL ends in "gazinta2.php"

    POST /plugin-io/api/vitalstream/gazinta2.php
    """
    @api.post("/gazinta2.php")
    def index(self) -> list[Response | Effect]:
        # Always accept, but we will only do anything if we can match the
        # request body to an active session.
        effects = [
            JSONResponse(
                {"message": "Reading accepted"}, status_code=HTTPStatus.ACCEPTED
            )
        ]

        # The session id is entered as the patient id on the device via QR
        # code
        session_id = self.request.json().get('patid')

        # Ensure the request body is referencing an active session
        cache = get_cache()
        session = cache.get(session_key(session_id))
        if session is not None:
            effects.append(Broadcast(message=self.request.text(), channel=session_id).apply())
        return effects
