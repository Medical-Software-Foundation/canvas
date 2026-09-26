"""Records a message transmission failure against the step that sent it."""

from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler
from canvas_sdk.v1.data.message import MessageTransmission

from medication_followup_protocol.models import EnrolledStep, StepStatus


class DeliveryWatcher(BaseHandler):
    """Mark a step failed when the message it sent did not arrive."""

    RESPONDS_TO = EventType.Name(EventType.MESSAGE_TRANSMISSION_UPDATED)

    def compute(self) -> list[Effect]:
        """Find the step that sent this message and record the failure against it."""
        transmission = MessageTransmission.objects.filter(id=self.event.target.id).first()
        if transmission is None or not transmission.failed:
            return []

        # Matched by the identifier of the message the step sent, which is what the
        # specification's data contract stores. Nothing populates that field today,
        # because the message effect hands no identifier back when it is applied. The
        # report names this, it is not routed around here.
        # transmission.message_id is the raw foreign key column, which is the message's
        # dbid rather than the identifier a plugin ever sees, so traverse to the message.
        message = transmission.message
        if message is None:
            return []

        step = EnrolledStep.objects.filter(message_id=str(message.id)).first()
        if step is None:
            return []

        step.status = StepStatus.FAILED
        step.failure_reason = (
            f"The message was not delivered over {transmission.contact_point_system}."
            if transmission.contact_point_system
            else "The message was not delivered."
        )
        step.save()
        return []
