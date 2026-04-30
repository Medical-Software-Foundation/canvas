from http import HTTPStatus

import arrow
import re

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import Broadcast, JSONResponse, Response
from canvas_sdk.handlers.simple_api import Credentials, SimpleAPI, api

from vitalstream.util import session_key


class CaretakerPortalAPI(SimpleAPI):
    """
    API for receiving readings from the VitalStream Device by Caretaker Medical.

    The Canvas SDK auth mixins (StaffSessionAuthMixin, APIKeyAuthMixin) don't
    fit this endpoint: the device posts directly to `/gazinta2.php` with its
    serial number embedded in the JSON body, with no way to send custom
    headers or API keys. Authentication is therefore payload-based — the
    serial number is matched against AUTHORIZED_SERIAL_NUMBERS (a secret)
    and the request's `patid` field must match an active cached session.
    """

    def authenticate(self, credentials: Credentials) -> bool:
        # Device cannot send Canvas session cookies or API key headers, so
        # the framework auth is bypassed. Actual authorization is enforced
        # inside `index()` via the serial-number + session lookups below.
        return True


    """
    The device requires the receiving endpoint URL ends in "gazinta2.php"

    POST /plugin-io/api/vitalstream/gazinta2.php
    """
    @api.post("/gazinta2.php")
    def index(self) -> list[Response | Effect]:
        try:
            body = self.request.json() or {}
        except (ValueError, TypeError):
            return [
                JSONResponse(
                    {"message": "Invalid JSON"}, status_code=HTTPStatus.BAD_REQUEST
                )
            ]
        if not isinstance(body, dict):
            return [
                JSONResponse(
                    {"message": "Invalid payload"}, status_code=HTTPStatus.BAD_REQUEST
                )
            ]

        raw_sn = body.get('sn')
        if not isinstance(raw_sn, str):
            return [
                JSONResponse(
                    {"message": "Unauthorized"}, status_code=HTTPStatus.UNAUTHORIZED
                )
            ]
        serial_number = raw_sn.lower()
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
        raw_patid = body.get('patid')
        if not isinstance(raw_patid, str) or not raw_patid.strip():
            return effects
        session_id = raw_patid.lower()

        # Ensure the request body is referencing an active session
        cache = get_cache()
        session = cache.get(session_key(session_id))
        if session is not None:
            # TODO: channel names do not currently support hyphens, so they're
            # being substituted with underscores. We need to broadcast to the
            # version that has underscores.
            session_id = session_id.replace("-", "_")

            # Parse the request payload and pull out measurements to record,
            # grouping by timestamp. Bad rows (missing/malformed `ts`) are
            # skipped rather than aborting the whole payload.
            measurements: dict = {}
            v1_readings = body.get('v1') or {}
            if isinstance(v1_readings, dict):
                for readings in v1_readings.values():
                    if not isinstance(readings, dict):
                        continue
                    ts = self._safe_iso8601(readings.get('ts'))
                    if ts is None:
                        continue
                    measurement = {}
                    if 'hr' in readings:
                        measurement['hr'] = readings['hr']
                    if 'sys' in readings:
                        measurement['sys'] = readings['sys']
                    if 'dia' in readings:
                        measurement['dia'] = readings['dia']
                    if 'resp' in readings:
                        measurement['resp'] = readings['resp']
                    measurements[ts] = measurement

            spo2_readings = body.get('spo2') or {}
            if isinstance(spo2_readings, dict):
                for reading in spo2_readings.values():
                    if not isinstance(reading, dict) or 'v' not in reading:
                        continue
                    ts = self._safe_iso8601(reading.get('ts'))
                    if ts is None:
                        continue
                    if ts not in measurements:
                        measurements[ts] = {}
                    measurements[ts]['spo2'] = reading['v']

            effects.append(Broadcast(message={'measurements': measurements}, channel=session_id).apply())
        return effects

    def _safe_iso8601(self, timestamp) -> str | None:
        if not isinstance(timestamp, str):
            return None
        try:
            return self.convert_timestamp_to_iso8601(timestamp)
        except (ValueError, arrow.parser.ParserError):
            return None

    def convert_timestamp_to_iso8601(self, timestamp) -> str:
        # Expects timestamp to be a string like '2026-Jan-07 08:50:14 UTC'
        # Returns '2026-01-07T08:50:14+00:00'
        return arrow.get(timestamp, 'YYYY-MMM-DD HH:mm:ss ZZZ').isoformat()
