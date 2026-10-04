from canvas_sdk.effects import Effect
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.v1.data import Note
from canvas_sdk.v1.data.note import NoteStateChangeEvent, NoteStates

from logger import log

from bp_cpt2.bp_claim_coder import get_llm_client, process_bp_billing_for_note
from bp_cpt2.utils import to_bool


class BloodPressureNoteButtonHandler(ActionButton):
    """
    Action button handler that links the note's hypertension-related assessments
    to its BP billing codes before the note is locked.
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
            log.info(f"Skipping BP assessment linking for note {note_id} - note type is not billable")
            return []

        return process_bp_billing_for_note(
            note=note,
            llm=get_llm_client(self.secrets),
            was_just_locked=False  # Manual button click: don't use cache
        )
