from http import HTTPStatus

import arrow
import re

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
        # Authentication is done based on the serial number and patient id
        # values present in each request payload. This authenticate method
        # will let everything through and defers to the actual request
        # handling to choose whether or not to accept the data.
        return True


    """
    The device requires the receiving endpoint URL ends in "gazinta2.php"

    POST /plugin-io/api/vitalstream/gazinta2.php
    """
    @api.post("/gazinta2.php")
    def index(self) -> list[Response | Effect]:
        # Check that the request contains a serial number listed in the plugin
        # secrets.
        serial_number = self.request.json().get('sn').lower()
        # Serial number in request must be at least one alphanumeric character
        # long and in the list of authorized serial numbers.
        if not (bool(re.search(r'\w+', serial_number)) and serial_number in self.secrets['AUTHORIZED_SERIAL_NUMBERS'].splitlines()):
            return [
                JSONResponse(
                    {"message": "Unauthorized"}, status_code=HTTPStatus.UNAUTHORIZED
                )
            ]

        # Always accept, but we will only do anything if we can match the
        # request body to an active session.
        effects = [
            JSONResponse(
                {"message": "Reading accepted"}, status_code=HTTPStatus.ACCEPTED
            )
        ]

        # The session id is entered as the patient id on the device via QR
        # code
        session_id = self.request.json().get('patid').lower()

        # Ensure the request body is referencing an active session
        cache = get_cache()
        session = cache.get(session_key(session_id))
        if session is not None:
            # TODO: channel names do not currently support hyphens, so they're
            # being substituted with underscores. We need to broadcast to the
            # version that has underscores.
            session_id = session_id.replace("-", "_")

            # Parse the request payload and pull out measurements to record,
            # grouping by timestamp
            measurements = {}
            for readings in self.request.json().get('v1', {}).values():
                measurement = {}
                if 'hr' in readings: 
                    measurement['hr'] = readings['hr']
                if 'sys' in readings:
                    measurement['sys'] = readings['sys']
                if 'dia' in readings:
                    measurement['dia'] = readings['dia']
                if 'resp' in readings:
                    measurement['resp'] = readings['resp']
                measurements[self.convert_timestamp_to_iso8601(readings['ts'])] = measurement
            
            for reading in self.request.json().get('spo2', {}).values():
                measurement_time = self.convert_timestamp_to_iso8601(reading['ts'])
                if measurement_time not in measurements:
                    measurements[measurement_time] = {}
                measurements[measurement_time]['spo2'] = reading['v']

            effects.append(Broadcast(message={'measurements': measurements}, channel=session_id).apply())
        return effects

    def convert_timestamp_to_iso8601(self, timestamp) -> str:
        # Expects timestamp to be a string like '2026-Jan-07 08:50:14 UTC'
        # Returns '2026-01-07T08:50:14+00:00'
        return arrow.get(timestamp, 'YYYY-MMM-DD HH:mm:ss ZZZ').isoformat()
