from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.handlers.simple_api.websocket import WebSocketAPI

from logger import log
from vitalstream.util import session_key

# Channels that any authenticated staff can subscribe to (no session required).
OPEN_CHANNELS = {"spravato_notify"}


class LiveObservationsChannel(WebSocketAPI):
    # Allow connections for real sessions OR open notification channels.
    def authenticate(self) -> bool:
        logged_in_user = self.websocket.logged_in_user
        if not logged_in_user or logged_in_user.get("type") != "Staff":
            log.info(f"[VitalStream WS] Auth rejected: no staff user")
            return False

        channel = self.websocket.channel.lower()
        log.info(f"[VitalStream WS] Auth request for channel: {channel}")

        # Open channels don't require a session.
        if channel in OPEN_CHANNELS:
            log.info(f"[VitalStream WS] Authenticated open channel: {channel}")
            return True

        # Session-based channels: the session must exist AND belong to the
        # staff member subscribing to the channel. Matching the HTTP-side
        # check in VitalstreamUIAPI.validate_session prevents another staff
        # from tapping into a live session feed they don't own.
        cache = get_cache()
        # TODO: channel names do not currently support hyphens, so they're
        # being substituted with underscores. A conversion back to hyphens is
        # necessary.
        session_id = channel.replace("_", "-")
        session = cache.get(session_key(session_id))
        if session is None:
            log.info(f"[VitalStream WS] Auth rejected: no session for {session_id}")
            return False
        if session.get("staff_id") != logged_in_user.get("id"):
            log.info(
                f"[VitalStream WS] Auth rejected: session {session_id} "
                f"staff_id does not match logged-in user"
            )
            return False
        return True
