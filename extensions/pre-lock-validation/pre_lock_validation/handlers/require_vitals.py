from canvas_sdk.effects import Effect
from canvas_sdk.effects.validation import EventValidationError
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data.command import Command
from logger import log


class RequireVitalsToLockHandler(BaseHandler):
    """Prevents locking a note unless it contains committed vitals."""

    RESPONDS_TO = EventType.Name(EventType.NOTE_STATE_CHANGE_EVENT_PRE_CREATE)

    def compute(self) -> list[Effect]:
        """Block note locking if no committed vitals command exists."""
        note_state = self.event.context.get("state")
        note_id = self.event.context.get("note_id")

        log.info(f"[RequireVitalsToLockHandler] Note {note_id} transitioning to state: {note_state}")

        # Only validate when trying to lock the note
        if note_state != "LKD":
            return []

        # Check for committed vitals command on this note
        vitals_commands = Command.objects.filter(
            note__id=note_id,
            schema_key="vitals",
            state="committed"
        )

        if not vitals_commands.exists():
            log.info(f"[RequireVitalsToLockHandler] Blocking lock - no committed vitals found for note {note_id}")
            validation_error = EventValidationError()
            validation_error.add_error("Cannot lock note: Vitals must be recorded and committed before locking.")
            return [validation_error.apply()]

        log.info(f"[RequireVitalsToLockHandler] Vitals found, allowing lock for note {note_id}")
        return []
