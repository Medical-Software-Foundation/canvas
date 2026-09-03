from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.utils import Http

from logger import log

# Note state that triggers the webhook. Canvas emits a note state change event for
# every transition (NEW, LKD, ULK, ...); we only care about a note being signed.
SIGNED_STATE = "SGN"


class NoteLockWebhookProtocol(BaseProtocol):
    """
    When a note is signed, POST its note id and patient id to an external endpoint.
    """

    RESPONDS_TO = EventType.Name(EventType.NOTE_STATE_CHANGE_EVENT_UPDATED)

    def compute(self) -> list[Effect]:
        """Send the signed note's identifiers to the configured webhook."""
        context = self.event.context
        state = context.get("state")

        if state != SIGNED_STATE:
            return []

        payload = {
            "state": state,
            "note_id": context.get("note_id"),
            "patient_id": context.get("patient_id"),
        }

        url = self.secrets["WEBHOOK_URL"]
        headers = {"Content-Type": "application/json"}

        auth_token = self.secrets.get("AUTH_TOKEN")
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"

        response = Http().post(url, json=payload, headers=headers)

        if response.ok:
            log.info(f"Sent signed note {payload['note_id']} to the webhook.")
        else:
            log.error(
                f"Webhook rejected signed note {payload['note_id']}: "
                f"{response.status_code}"
            )

        return []
