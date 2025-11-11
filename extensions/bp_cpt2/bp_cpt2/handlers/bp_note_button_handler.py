from canvas_sdk.effects import Effect
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.v1.data import Note
from canvas_sdk.v1.data.note import NoteStateChangeEvent, NoteStates

from logger import log

from bp_cpt2.bp_claim_coder import process_bp_billing_for_note
from bp_cpt2.utils import to_bool


class BloodPressureNoteButtonHandler(ActionButton):
    """
    Action button handler that processes BP billing codes when clicked.

    This handler provides a manual trigger to:
    - Update assessment links for existing BP billing codes
    - Analyze treatment plans for uncontrolled BP
    - Add appropriate treatment plan codes (G8753-G8755)

    Unlike the note state handler, this does NOT push charges - it only adds the billing codes.
    """

    BUTTON_TITLE = "BP CPT-II"
    BUTTON_KEY = "BP_CPT_II_ANALYZE"
    BUTTON_LOCATION = ActionButton.ButtonLocation.NOTE_HEADER

    def visible(self) -> bool:
        """Control button visibility based on SHOW_BUTTON_FOR_MANUAL_TRIGGER secret and note editability."""
        show_button = self.secrets.get('SHOW_BUTTON_FOR_MANUAL_TRIGGER', '')
        if not to_bool(show_button):
            return False

        note_id = self.event.context.get('note_id')
        current_note_state = NoteStateChangeEvent.objects.filter(note_id=note_id).order_by("created").last()
        return bool(
            current_note_state
            and current_note_state.state
            in [
                NoteStates.NEW,
                NoteStates.PUSHED,
                NoteStates.UNLOCKED,
                NoteStates.RESTORED,
                NoteStates.UNDELETED,
                NoteStates.CONVERTED,
            ]
        )

    def handle(self) -> list[Effect]:
        """Handle button click - process BP billing codes for the note."""
        # Get note_id from context
        note_id = self.event.context.get('note_id')
        if not note_id:
            log.error("No note_id in context")
            return []

        log.info(f"BP CPT-II button clicked for note {note_id}")

        # Get the note
        try:
            note = Note.objects.get(dbid=note_id)
        except Note.DoesNotExist:
            log.error(f"Note {note_id} not found")
            return []

        # Check if note is billable
        if note.note_type_version and not note.note_type_version.is_billable:
            log.info(f"Skipping BP treatment analysis for note {note_id} - note type is not billable")
            return []

        # Use shared utility function to process BP billing codes
        openai_api_key = self.secrets.get('OPENAI_API_KEY')
        include_treatment_codes = to_bool(self.secrets.get('INCLUDE_TREATMENT_PLAN_CODES', ''))

        return process_bp_billing_for_note(
            note=note,
            openai_api_key=openai_api_key,
            include_treatment_codes=include_treatment_codes,
            was_just_locked=False  # Manual button click: don't push charges or use cache
        )
