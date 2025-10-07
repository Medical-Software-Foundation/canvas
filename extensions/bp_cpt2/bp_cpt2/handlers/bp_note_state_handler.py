from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from logger import log


class BloodPressureNoteStateHandler(BaseHandler):
    """
    Handles note state changes for treatment plan documentation analysis.

    This handler is reserved for future implementation of treatment plan codes
    (G8753-G8755) which require analyzing note content for treatment plan documentation.

    Currently, all BP measurement codes (3074F-3080F, G8783, G8784, G8950, G8951, G8752)
    are handled by the BloodPressureVitalsHandler when vitals are committed.
    """

    RESPONDS_TO = [
        EventType.Name(EventType.NOTE_STATE_CHANGE_EVENT_CREATED)
    ]

    def compute(self) -> list[Effect]:
        """Main compute method called when note state changes."""
        # Get note state and note_id from context
        new_note_state = self.event.context.get('state')
        note_id = self.event.context.get('note_id')

        log.info(f"Note {note_id} state change to: {new_note_state}")

        # Only process when note is being locked (about to be finalized)
        if new_note_state != 'LKD':
            log.info(f"Skipping BP billing for note {note_id} - state is {new_note_state}, not LKD")
            return []

        # This handler is currently not implemented for blood pressure billing codes.
        # The vitals handler (BloodPressureVitalsHandler) handles all BP measurement codes
        # (3074F-3080F, G8783, G8784, G8950, G8951, G8752) when vitals are committed.
        #
        # This handler could be enhanced to:
        # 1. Add treatment plan codes (G8753-G8755) by analyzing note content for treatment plans
        # 2. Add diagnosis pointers to billing codes by analyzing documented diagnoses in the note
        #
        # These enhancements are not currently implemented.
        log.info(f"Note state handler for note {note_id} - treatment plan and diagnosis pointer analysis not implemented. "
                 f"All BP measurement codes are handled by the vitals handler.")

        return []
