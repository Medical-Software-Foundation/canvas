from canvas_sdk.effects import Effect
from canvas_sdk.effects.action_button import ReloadNoteActionButtonsEffect
from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler

from logger import log


class ReloadButtonsOnNoteStateChange(BaseHandler):
    """Reloads a note's action buttons each time the note changes state, which
    re-evaluates CommitButtonHandler.visible() without a page refresh."""

    RESPONDS_TO = EventType.Name(EventType.NOTE_STATE_CHANGE_EVENT_CREATED)

    def compute(self) -> list[Effect]:
        note_id = self.event.context.get("note_id")
        if not note_id:
            log.warning("Note state change event has no note_id; buttons not reloaded")
            return []
        return [ReloadNoteActionButtonsEffect(id=note_id).apply()]
