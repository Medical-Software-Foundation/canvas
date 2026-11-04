from canvas_sdk.effects import Effect
from canvas_sdk.effects.action_button import ReloadNoteActionButtonsEffect
from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler


class ReloadButtonOnNoteStateChange(BaseHandler):
    """Re-check the note header buttons when a note changes state.

    The Conditional Questionnaire button only shows on notes that can be edited. Without a
    reload, locking or signing a note leaves the button on screen until the page is reloaded.
    """

    RESPONDS_TO = EventType.Name(EventType.NOTE_STATE_CHANGE_EVENT_CREATED)

    def compute(self) -> list[Effect]:
        """Reload the note's action buttons so the header button's visibility is recomputed."""
        note_id = self.event.context.get("note_id")
        if not note_id:
            return []
        return [ReloadNoteActionButtonsEffect(id=str(note_id)).apply()]
