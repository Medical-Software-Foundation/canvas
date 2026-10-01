"""Filter message note types from the patient timeline."""
from canvas_sdk.effects import Effect
from canvas_sdk.effects.patient.timeline import PatientTimelineEffect
from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler
from canvas_sdk.v1.data.note import NoteType

_MESSAGE_NOTE_TYPE_NAME = "Message"


class TimelineMessageFilter(BaseHandler):
    """Always hide message notes from the patient timeline."""

    RESPONDS_TO = [EventType.Name(EventType.PATIENT_TIMELINE__GET_CONFIGURATION)]

    def compute(self) -> list[Effect]:
        msg_note_type = NoteType.objects.filter(
            name=_MESSAGE_NOTE_TYPE_NAME, is_active=True
        ).first()

        if not msg_note_type or not msg_note_type.unique_identifier:
            return []

        effect = PatientTimelineEffect(
            excluded_note_types=[str(msg_note_type.unique_identifier)]
        )
        return [effect.apply()]
