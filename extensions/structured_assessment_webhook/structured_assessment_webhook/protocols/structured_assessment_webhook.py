from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.utils import Http

from logger import log

# ---------------------------------------------------------------------------
# Instance-specific configuration.
#
# This plugin fires on a single answer to a single question of a single
# structured assessment. All three values below come from *our* Canvas
# instance -- replace them with the assessment title, question ID, and answer
# ID from your own. You can find the IDs in the assessment's definition in the
# Canvas admin UI.
# ---------------------------------------------------------------------------
ASSESSMENT_TITLE = "Health Coaching ABT"
QUESTION_KEY = "question-3973"
ANSWER_ID = 7550


# Inherit from BaseProtocol to properly get registered for events
class StructuredAssessmentWebhookProtocol(BaseProtocol):
    """Watches for a committed 'Health Coaching ABT' structured assessment where question-3973
	equals 7550, and notifies the external API so the encounter can be counted toward CCM 		minutes and sent to CCIQ."""

    # Name the event type you wish to run in response to
    RESPONDS_TO = EventType.Name(EventType.STRUCTURED_ASSESSMENT_COMMAND__POST_COMMIT)

    def compute(self) -> list[Effect]:
        """This method gets called when an event of the type RESPONDS_TO is fired."""
        context = self.event.context
        fields = context.get("fields")

        if not fields:
            return []

        questionnaire_text = fields.get("questionnaire", {}).get("text")
        if questionnaire_text != ASSESSMENT_TITLE:
            return []

        if fields.get(QUESTION_KEY) != ANSWER_ID:
            return []

        url = self.secrets.get("WEBHOOK_URL")
        if not url:
            log.error("WEBHOOK_URL is not set; skipping structured assessment webhook.")
            return []

        payload = {
            "contents": {
                "note_id": (context.get("note") or {}).get("id"),
                "patient_id": (context.get("patient") or {}).get("id"),
            }
        }

        headers = {"Content-Type": "application/json"}

        auth_token = self.secrets.get("AUTH_TOKEN")
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"

        response = Http().post(url, json=payload, headers=headers)

        if response.ok:
            log.info("Successfully sent structured assessment CCM data.")
        else:
            log.error(
                f"Webhook rejected structured assessment CCM data: "
                f"{response.status_code}"
            )

        return []
