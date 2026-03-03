import uuid

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data import Questionnaire
from canvas_sdk.v1.data.note import CurrentNoteStateEvent, Note


class HealthRiskAssessmentButton(ActionButton):
    """ActionButton that launches the Health Risk Assessment questionnaire modal."""

    BUTTON_TITLE = "Health Risk Assessment"
    BUTTON_KEY = "COMPLETE_HRA"
    BUTTON_LOCATION = ActionButton.ButtonLocation.NOTE_HEADER

    QUESTIONNAIRE_CODE = "HRA_AWV"
    QUESTIONNAIRE_CODE_SYSTEM = "INTERNAL"
    CUSTOM_COMMAND_SCHEMA_KEY = "healthRiskAssessmentSummary"

    # Allowed note states for showing the HRA button
    # NEW=Created, PSH=Pushed, ULK=Unlocked, RST=Restored, UND=Undeleted, CVD=Converted
    ALLOWED_NOTE_STATES = {"NEW", "PSH", "ULK", "RST", "UND", "CVD"}

    def visible(self) -> bool:
        """Show button only for editable notes without an existing HRA."""
        try:
            note_id = self.context.get("note_id")
            if not note_id:
                return False

            # Check note is in an allowed state
            note_state_event = CurrentNoteStateEvent.objects.get(note__dbid=note_id)
            if note_state_event.state not in self.ALLOWED_NOTE_STATES:
                return False

            # Check if HRA already exists in this note (either as questionnaire or custom command)
            note = Note.objects.get(dbid=note_id)

            # Check for custom command (healthRiskAssessmentSummary)
            custom_commands = note.commands.filter(schema_key=self.CUSTOM_COMMAND_SCHEMA_KEY)
            if custom_commands.exists():
                return False

            # Check for questionnaire command with HRA
            questionnaire_commands = note.commands.filter(schema_key="questionnaire")
            for command in questionnaire_commands:
                command_data = command.data or {}

                # The questionnaire info is nested under 'questionnaire' key
                questionnaire_info = command_data.get("questionnaire", {})
                questionnaire_name = questionnaire_info.get("text", "")
                questionnaire_extra = questionnaire_info.get("extra", {})
                questionnaire_extra_name = questionnaire_extra.get("name", "")

                # Check if this is an HRA questionnaire by name
                if "Health Risk Assessment" in questionnaire_name:
                    return False
                if "Health Risk Assessment" in questionnaire_extra_name:
                    return False

            return True
        except (CurrentNoteStateEvent.DoesNotExist, Note.DoesNotExist):
            return False

    def handle(self) -> list[Effect]:
        """Launch the Health Risk Assessment modal when button is clicked."""
        note_id = self.context.get("note_id")
        patient_id = self.target

        # Get the ACTIVE questionnaire ID for the HRA
        questionnaire = Questionnaire.objects.filter(
            code=self.QUESTIONNAIRE_CODE,
            code_system=self.QUESTIONNAIRE_CODE_SYSTEM,
            status="AC",
        ).first()

        questionnaire_id = str(questionnaire.id) if questionnaire else ""

        # Generate a unique command UUID for this assessment
        command_uuid = str(uuid.uuid4())

        # Render the assessment form template
        context = {
            "note_id": note_id,
            "patient_id": patient_id,
            "questionnaire_id": questionnaire_id,
            "command_uuid": command_uuid,
        }

        html_content = render_to_string(
            "templates/assessment_form.html",
            context,
        )

        modal = LaunchModalEffect(
            content=html_content,
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
        )

        return [modal.apply()]
