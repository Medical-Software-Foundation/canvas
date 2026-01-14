from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.handlers.simple_api.websocket import WebSocketAPI

from vitalstream.util import session_key


class LiveObservationsChannel(WebSocketAPI):
    # Only allow connections for real sessions and logged-in staff.
    def authenticate(self) -> bool:
        cache = get_cache()

        # TODO: channel names do not currently support hyphens, so they're
        # being substituted with underscores. A conversion back to hyphens is
        # necessary.
        session_id = self.websocket.channel.lower()
        session_id = session_id.replace("_", "-")

        session = cache.get(session_key(session_id))
        logged_in_user = self.websocket.logged_in_user
        return session is not None and logged_in_user["type"] == "Staff"
