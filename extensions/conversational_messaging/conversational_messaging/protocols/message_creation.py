import requests

from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.v1.data.message import MessageTransmission

from logger import log


class MessageCreateProtocol(BaseProtocol):
    RESPONDS_TO = [
      EventType.Name(EventType.MESSAGE_TRANSMISSION_CREATED)
    ]

    def compute(self) -> list[Effect]:
        url = f"https://{self.environment['CUSTOMER_IDENTIFIER']}.canvasmedical.com/plugin-io/api/conversational_messaging/message/received"
        message = MessageTransmission.objects.get(id=self.target).message

        if message.note.patient:
            log.info(f"Sending notification that message {self.target} was received for patient {message.note.patient.id}")
            # Send a message to the endpoint that broadcasts to websocket subscriptions.
            response = requests.post(
                url,
                json={"msg": "message_received", "message_id": self.target, "patient_id": message.note.patient.id},
                headers={"Authorization": self.secrets["simpleapi-api-key"]}
            )
            log.info(response.status_code)
            log.info(response.content)
        else:
            log.error("Patient not found associated with message note")
        return []
