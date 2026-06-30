from canvas_sdk.effects import Effect
from canvas_sdk.effects.action_button import ReloadNoteActionButtonsEffect
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data.command import Command


class ReloadFooterOnCommandCommit(BaseHandler):
    """Reload the note footer whenever any command is committed.

    ``SignNoteButton`` hides itself while the note still has staged (uncommitted)
    commands. Committing a command does not on its own re-evaluate the footer, so this
    handler reloads it on every command's POST_COMMIT event — the Sign button reappears
    as soon as the last staged command is committed, without a page refresh.
    """

    RESPONDS_TO = [
        EventType.Name(value)
        for value in EventType.values()
        if EventType.Name(value).endswith("_COMMAND__POST_COMMIT")
    ]

    def compute(self) -> list[Effect]:
        """Reload the footer buttons for the committed command's note."""
        command = Command.objects.filter(id=self.event.target.id).first()
        if not command or not command.note:
            return []

        return [ReloadNoteActionButtonsEffect(id=str(command.note.id)).apply()]


class ReloadFooterOnNoteStateChange(BaseHandler):
    """Reload the note footer whenever the note transitions to a new state.

    Keeps the state-responsive buttons in sync when the note's state changes through any
    path, not just a footer-button click (for example a lock or sign performed elsewhere).
    """

    RESPONDS_TO = EventType.Name(EventType.NOTE_STATE_CHANGE_EVENT_CREATED)

    def compute(self) -> list[Effect]:
        """Reload the footer buttons for the note whose state changed."""
        note_id = self.event.context.get("note_id")
        if not note_id:
            return []
        return [ReloadNoteActionButtonsEffect(id=note_id).apply()]
