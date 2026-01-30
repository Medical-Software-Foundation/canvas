from canvas_sdk.effects import Effect
from canvas_sdk.effects.validation import EventValidationError
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data.command import Command
from logger import log


class NoStagedCommandsToLockHandler(BaseHandler):
    """Prevents locking a note if there are any staged commands."""

    RESPONDS_TO = EventType.Name(EventType.NOTE_STATE_CHANGE_EVENT_PRE_CREATE)

    def compute(self) -> list[Effect]:
        """Block note locking if any staged commands exist."""
        note_state = self.event.context.get("state")
        note_id = self.event.context.get("note_id")

        log.info(f"[NoStagedCommandsToLockHandler] Note {note_id} transitioning to state: {note_state}")

        # Only validate when trying to lock the note
        if note_state != "LKD":
            return []

        # Check for any staged commands on this note
        # RFV command are excluded from this validation because they are not committable
        staged_commands = list(Command.objects.exclude(schema_key='reasonForVisit').filter(
            note__id=note_id,
            state="staged"
        ))

        if staged_commands:
            count = len(staged_commands)
            schema_keys = {cmd.schema_key for cmd in staged_commands}
            keys_display = ", ".join(list(schema_keys))

            log.info(f"[NoStagedCommandsToLockHandler] Blocking lock - {count} staged commands found for note {note_id}: {keys_display}")
            validation_error = EventValidationError()
            validation_error.add_error(
                f"Cannot lock note: {count} staged command(s) must be committed or removed before locking. "
                f"Staged command types: {keys_display}"
            )
            return [validation_error.apply()]

        log.info(f"[NoStagedCommandsToLockHandler] No staged commands, allowing lock for note {note_id}")
        return []
