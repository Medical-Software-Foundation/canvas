from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.handlers.simple_api.websocket import WebSocketAPI

from vitalstream.util import session_key


class LiveObservationsChannel(WebSocketAPI):
    # Only allow connections for real sessions and logged-in staff.
    def authenticate(self) -> bool:
        cache = get_cache()
        session = cache.get(session_key(self.websocket.channel))
        logged_in_user = self.websocket.logged_in_user
        return session is not None and logged_in_user["type"] == "Staff"
