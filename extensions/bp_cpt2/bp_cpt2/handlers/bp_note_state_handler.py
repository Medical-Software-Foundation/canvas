from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data import Note
from canvas_sdk.v1.data.note import NoteStates

from logger import log

from bp_cpt2.bp_claim_coder import process_bp_billing_for_note
from bp_cpt2.utils import to_bool


class BloodPressureNoteStateHandler(BaseHandler):
    """
    Handles note state changes for treatment plan documentation analysis.

    This handler analyzes clinical notes to determine if blood pressure treatment plans
    are documented and adds appropriate billing codes (G8753-G8755) for uncontrolled BP.

    Treatment codes:
    - G8753: Most recent BP >= 140/90 and treatment plan documented
    - G8754: Most recent BP >= 140/90 and no treatment plan, reason not given
    - G8755: Most recent BP >= 140/90 and no treatment plan, documented reason
    """

    RESPONDS_TO = [
        EventType.Name(EventType.NOTE_STATE_CHANGE_EVENT_UPDATED)
    ]

    def compute(self) -> list[Effect]:
        """Main compute method called when note state changes."""
        # Get note state and note_id from event
        new_note_state = self.event.context.get('state')
        note_id = self.event.context.get('note_id')

        log.info(f"Note {note_id} state change to: {new_note_state}")

        # Only process when note is locked
        if new_note_state != NoteStates.LOCKED:
            log.info(f"Skipping BP treatment analysis for note {note_id} - state is {new_note_state}")
            return []

        # Get the note
        try:
            note = Note.objects.get(id=note_id)
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
            was_just_locked=True  # Push charges and use cache for deduplication
        )
