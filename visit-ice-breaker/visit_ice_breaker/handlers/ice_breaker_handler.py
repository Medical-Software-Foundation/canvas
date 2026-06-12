from canvas_sdk.commands import InstructCommand
from canvas_sdk.commands.constants import CodeSystems, Coding
from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data.note import Note
from canvas_sdk.v1.data.patient import Patient

from visit_ice_breaker.question_tracker import QuestionTracker
from visit_ice_breaker.structures.age_group import AgeGroup


class IceBreakerHandler(BaseHandler):
    RESPONDS_TO = EventType.Name(EventType.NOTE_STATE_CHANGE_EVENT_CREATED)

    def compute(self) -> list[Effect]:
        note_state: str | None = self.event.context.get("state")
        if note_state != "NEW":
            return []

        note_id: int = self.event.context.get("note_id")
        note: Note = Note.objects.select_related("note_type_version").get(id=note_id)

        note_type_name: str = note.note_type_version.name
        if note_type_name != "Office visit":
            return []

        note_uuid: str = str(note.id)
        patient_id: str = self.event.context.get("patient_id")
        patient: Patient = Patient.objects.get(id=patient_id)
        age_group: AgeGroup = AgeGroup.from_birth_date(patient.birth_date)

        question = QuestionTracker.get_or_select_question(
            note_id=note_uuid,
            patient_id=patient_id,
            age_group=age_group,
        )

        display_text: str = f"[{question.category}] {question.text}"

        command: InstructCommand = InstructCommand(
            note_uuid=note_uuid,
            coding=Coding(
                system=CodeSystems.UNSTRUCTURED,
                code=display_text,
            ),
            comment="",
        )

        result: list[Effect] = [command.originate()]
        return result
