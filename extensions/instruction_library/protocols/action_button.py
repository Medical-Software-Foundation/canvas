"""Action button that launches the patient instructions modal from a note."""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.note import Note

from logger import log


class PatientInstructionsButton(ActionButton):
    """Button in note header that opens the instructions picker."""

    BUTTON_TITLE = "Instructions"
    BUTTON_KEY = "patient_instructions_picker"
    BUTTON_LOCATION = ActionButton.ButtonLocation.NOTE_HEADER

    def handle(self) -> list[Effect]:
        note_id = self.context.get("note_id")
        patient_id = self.event.target.id

        if not note_id:
            log.warning("[PI] No note_id in action button context")
            return []

        # Look up the note UUID for InstructCommand
        try:
            note = Note.objects.get(dbid=note_id)
            note_uuid = str(note.id)
        except Note.DoesNotExist:
            log.warning("[PI] Note dbid %s not found" % note_id)
            return []

        html = render_to_string(
            "templates/patient_instructions.html",
            {
                "note_uuid": note_uuid,
                "patient_id": patient_id or "",
            },
        )

        return [
            LaunchModalEffect(
                content=html,
                target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE,
                title="Patient Instructions",
            ).apply()
        ]
