from typing import ClassVar

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import Broadcast
from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler
from canvas_sdk.v1.data.message import Message


class NewMessageNotifier(BaseHandler):
    """Broadcasts a new-message notification to the staff side's WS channel.

    Fires on every MESSAGE_CREATED event. When exactly one side is a Staff
    and the other is a Patient, the staff's open companion-app clients are
    pushed `{"type":"new_message","patient_id":<uuid>,"message_id":<uuid>}`
    so they can refresh the affected thread.
    """

    RESPONDS_TO: ClassVar[list[str]] = [EventType.Name(EventType.MESSAGE_CREATED)]

    def compute(self) -> list[Effect]:
        message_id = self.event.target.id
        message = (
            Message.objects.select_related(
                "sender", "sender__staff", "sender__patient",
                "recipient", "recipient__staff", "recipient__patient",
            )
            .filter(id=message_id)
            .first()
        )
        if message is None or message.sender is None or message.recipient is None:
            return []

        staff = self._staff_side(message.sender, message.recipient)
        patient = self._patient_side(message.sender, message.recipient)
        if staff is None or patient is None:
            return []

        return [
            Broadcast(
                channel=f"staff-{staff.id}",
                message={
                    "type": "new_message",
                    "patient_id": str(patient.id),
                    "message_id": str(message.id),
                },
            ).apply()
        ]

    @staticmethod
    def _staff_side(sender, recipient):
        if sender.is_staff and not recipient.is_staff:
            return sender.person_subclass
        if recipient.is_staff and not sender.is_staff:
            return recipient.person_subclass
        return None

    @staticmethod
    def _patient_side(sender, recipient):
        if sender.is_staff and not recipient.is_staff:
            return recipient.person_subclass
        if recipient.is_staff and not sender.is_staff:
            return sender.person_subclass
        return None
