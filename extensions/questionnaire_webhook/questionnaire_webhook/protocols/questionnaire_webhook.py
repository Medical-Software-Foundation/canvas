from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.utils import Http

from logger import log

# ---------------------------------------------------------------------------
# Instance-specific configuration.
#
# Branch A is gated on a single answer to a single question. The question and
# answer IDs below come from the questionnaire in *our* Canvas instance --
# replace them with the question ID and answer ID from your own questionnaire.
# You can find them in the questionnaire's definition in the Canvas admin UI.
# ---------------------------------------------------------------------------
CCM_QUESTIONNAIRE_TITLE = "RDP Encounter Type"
CCM_QUESTION_KEY = "question-3331"
CCM_ANSWER_ID = 6702

# Branch B matches on a title prefix rather than an exact title, so it picks up
# every prior-authorization questionnaire regardless of the rest of its name.
PA_TITLE_PREFIX = "PA"

# Question labels on the PA questionnaire, mapped to the keys they become in the
# outgoing payload. Labels must match the questionnaire exactly; anything not
# listed here is ignored.
LABEL_TO_PAYLOAD_KEY = {
    "Days Supply": "days_supply",
    "Quantity": "quantity",
    "Directions": "directions",
    "Drug Name": "drug_name",
    "Strength": "strength",
    "Dose Form": "dose_form",
    "Dispense Unit": "dispense_unit",
    "Route of Administration": "route_of_administration",
    "Prescription Date": "prescription_date",
}


# Inherit from BaseProtocol to properly get registered for events
class QuestionnaireWebhookProtocol(BaseProtocol):
    """Fires on questionnaire commit. Handles two cases: (1) 'RDP Encounter Type' questionnaires
	where question-3331 equals 6702 are flagged as CCM-eligible minutes; (2) any 			questionnaire whose title starts with 'PA' has its medication fields (drug, dose, 		quantity, etc.) extracted and saved to the external system for later prior-authorization 	processing."""

    # Name the event type you wish to run in response to
    RESPONDS_TO = EventType.Name(EventType.QUESTIONNAIRE_COMMAND__POST_COMMIT)

    def compute(self) -> list[Effect]:
        """This method gets called when an event of the type RESPONDS_TO is fired."""
        context = self.event.context
        fields = context.get("fields")

        if not fields:
            return []

        questionnaire_text = fields.get("questionnaire", {}).get("text")

        # Neither branch can match a questionnaire with no title.
        if not isinstance(questionnaire_text, str):
            return []

        note_id = (context.get("note") or {}).get("id")
        patient_id = (context.get("patient") or {}).get("id")

        # ---- Branch A: CCM-eligible minutes ----
        if questionnaire_text == CCM_QUESTIONNAIRE_TITLE:
            if fields.get(CCM_QUESTION_KEY) != CCM_ANSWER_ID:
                return []

            self._post(
                secret_name="CCM_WEBHOOK_URL",
                description="CCM RDP Encounter Type questionnaire",
                payload={
                    "contents": {
                        "note_id": note_id,
                        "patient_id": patient_id,
                    }
                },
            )

        # ---- Branch B: prior-authorization medication fields ----
        elif questionnaire_text.startswith(PA_TITLE_PREFIX):
            questions = (
                fields.get("questionnaire", {}).get("extra", {}).get("questions") or []
            )

            questionnaire_payload = {}
            for question in questions:
                label = question.get("label")

                # Skip anything we don't care about
                if label not in LABEL_TO_PAYLOAD_KEY:
                    continue

                # Safely extract option label
                options = question.get("options") or []
                questionnaire_payload[LABEL_TO_PAYLOAD_KEY[label]] = (
                    options[0].get("label") if options else None
                )

            self._post(
                secret_name="PA_WEBHOOK_URL",
                description="medication PA questionnaire",
                payload={
                    "contents": {
                        "note_id": note_id,
                        "patient_id": patient_id,
                        "questionnaire": questionnaire_payload,
                        "questionnaire_id": getattr(self.event.target, "id", None),
                    }
                },
            )

        return []

    def _post(self, *, secret_name: str, description: str, payload: dict) -> None:
        """POST a payload to the URL held in the named secret, and log the result."""
        url = self.secrets.get(secret_name)
        if not url:
            log.error(f"{secret_name} is not set; skipping {description}.")
            return

        headers = {"Content-Type": "application/json"}

        auth_token = self.secrets.get("AUTH_TOKEN")
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"

        response = Http().post(url, json=payload, headers=headers)

        if response.ok:
            log.info(f"Successfully sent {description} data.")
        else:
            log.error(f"Webhook rejected {description} data: {response.status_code}")
