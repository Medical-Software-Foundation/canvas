from canvas_sdk.effects import Effect
from canvas_sdk.effects.action_button import ReloadNoteActionButtonsEffect
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler

# Command lifecycle events that change a note's set of staged commands: a command being
# added (originated), removed, or committed. SignNoteButton gates on staged commands, so the
# footer must reload on each of these to keep the Sign gate in sync — not just on commit.
_COMMAND_CHANGE_SUFFIXES = (
    "_COMMAND__POST_ORIGINATE",
    "_COMMAND__POST_DELETE",
    "_COMMAND__POST_COMMIT",
)


class ReloadFooterOnCommandChange(BaseHandler):
    """Reload the note footer when a command is added to, removed from, or committed in the note.

    ``SignNoteButton`` hides itself while the note still has staged (uncommitted) commands.
    A change to the note's command set does not on its own re-evaluate the footer, so this
    handler reloads it whenever a command is added, removed, or committed — Sign hides as soon
    as a command is added and reappears once the last staged command is committed or removed,
    without a page refresh.
    """

    RESPONDS_TO = [
        EventType.Name(value)
        for value in EventType.values()
        if EventType.Name(value).endswith(_COMMAND_CHANGE_SUFFIXES)
    ]

    def compute(self) -> list[Effect]:
        """Reload the footer buttons for the note the changed command belongs to.

        The note's external id comes from the event context (``note.uuid``) rather than from
        the command itself — on a delete the command is already gone, so looking it up would
        find nothing and the footer would never reload.
        """
        note_id = (self.event.context.get("note") or {}).get("uuid")
        if not note_id:
            return []

        return [ReloadNoteActionButtonsEffect(id=note_id).apply()]


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
