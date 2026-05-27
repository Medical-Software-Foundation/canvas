from canvas_sdk.handlers.simple_api.websocket import WebSocketAPI
from canvas_sdk.v1.data.note import Note

from logger import log

from vitalstream.models import VitalstreamSession

# Prefix for per-note Spravato charting-app notification channels. The full
# channel name is `spravato_notify_<note_uuid_with_underscores>`; the unguessable
# UUID acts as the capability token so staff cannot enumerate other patients'
# notes from this channel.
SPRAVATO_NOTIFY_PREFIX = "spravato_notify_"


class LiveObservationsChannel(WebSocketAPI):
    """WebSocket channel for streaming readings to the UI and notifying it
    when the session is closed.

    Authorizes two channel shapes:
      - VitalStream session channels: name == session_id with hyphens
        substituted for underscores. The session_id is an unguessable UUID
        so its existence in the DB is sufficient authorization.
      - Per-note Spravato notification channels: spravato_notify_<note_uuid>.
        Note UUID acts as the capability token.
    """

    def authenticate(self) -> bool:
        logged_in_user = self.websocket.logged_in_user
        if not logged_in_user or logged_in_user.get("type") != "Staff":
            log.info("[VitalStream WS] Auth rejected: no staff user")
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

        # TODO: channel names do not currently support hyphens, so they're
        # being substituted with underscores. A conversion back to hyphens is
        # necessary.
        session_id = channel.replace("_", "-")
        if not VitalstreamSession.objects.filter(session_id=session_id).exists():
            log.info(f"[VitalStream WS] Auth rejected: no session for {session_id}")
            return False
        return True
