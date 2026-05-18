from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.handlers.simple_api.websocket import WebSocketAPI
from canvas_sdk.v1.data.note import Note

from logger import log
from vitalstream.util import session_key

# Prefix for per-note Spravato charting-app notification channels. The full
# channel name is `spravato_notify_<note_uuid_with_underscores>`; the unguessable
# UUID acts as the capability token so staff cannot enumerate other patients'
# notes from this channel.
SPRAVATO_NOTIFY_PREFIX = "spravato_notify_"


class LiveObservationsChannel(WebSocketAPI):
    # Allow connections for real device sessions OR per-note spravato_notify
    # channels (the note UUID acts as the capability token).
    def authenticate(self) -> bool:
        logged_in_user = self.websocket.logged_in_user
        if not logged_in_user or logged_in_user.get("type") != "Staff":
            log.info(f"[VitalStream WS] Auth rejected: no staff user")
            return False

        channel = self.websocket.channel.lower()
        log.info(f"[VitalStream WS] Auth request for channel: {channel}")

        # Per-note Spravato notification channels. The note UUID in the channel
        # name is the capability — verify the note exists so an attacker can't
        # park on a random channel name hoping for a future collision.
        if channel.startswith(SPRAVATO_NOTIFY_PREFIX):
            note_uuid = channel[len(SPRAVATO_NOTIFY_PREFIX):].replace("_", "-")
            if not Note.objects.filter(id=note_uuid).exists():
                log.info(f"[VitalStream WS] Auth rejected: no note {note_uuid}")
                return False
            return True

        cache = get_cache()
        # TODO: channel names do not currently support hyphens, so they're
        # being substituted with underscores. A conversion back to hyphens is
        # necessary.
        session_id = channel.replace("_", "-")
        session = cache.get(session_key(session_id))
        if session is None:
            log.info(f"[VitalStream WS] Auth rejected: no session for {session_id}")
            return False
        return True
