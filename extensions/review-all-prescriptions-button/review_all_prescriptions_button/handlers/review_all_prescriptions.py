"""Note header button that puts every staged prescription in the note into review.

Review is not signing. The prescriber still signs and sends each order in the note
themselves. The SDK has no sign effect for prescribing commands, so this plugin cannot
and does not sign or send anything.
"""

from canvas_sdk.commands import PrescribeCommand
from canvas_sdk.effects import Effect
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.compound_medication import CompoundMedication
from canvas_sdk.v1.data.note import CurrentNoteStateEvent, NoteStates
from logger import log

# Off by default: the button shows only when this plugin variable is exactly "true".
ENABLED_VARIABLE = "REVIEW_ALL_PRESCRIPTIONS_ENABLED"

# Schema key -> command class. Prescribe only: the SDK docs say review() "can only be
# called on Prescribe commands objects. Other command types do not support this
# operation." Refill and Adjust Prescription are left for the prescriber to review.
REVIEWABLE_COMMANDS = {
    PrescribeCommand.Meta.key: PrescribeCommand,
}

# Where a Prescribe command keeps its medication.
MEDICATION_FIELDS = ("prescribe",)

# The only state a command can be moved into review from.
STAGED = "staged"
NOT_CONTROLLED = CompoundMedication.ControlledSubstanceOptions.SCHEDULE_NOT_SCHEDULED


class ReviewAllPrescriptionsButton(ActionButton):
    """Puts every staged Prescribe command in the note into review."""

    BUTTON_TITLE = "Review all prescriptions"
    BUTTON_KEY = "REVIEW_ALL_PRESCRIPTIONS"
    BUTTON_LOCATION = ActionButton.ButtonLocation.NOTE_HEADER

    def _enabled(self) -> bool:
        """Fail closed: anything other than an explicit "true" keeps the button off."""
        value = self.secrets.get(ENABLED_VARIABLE) or ""
        return value.strip().lower() == "true"

    def _note_is_open(self, note_dbid: int | str) -> bool:
        """True when the note exists and is not locked."""
        try:
            state = CurrentNoteStateEvent.objects.get(note__dbid=note_dbid)
        except CurrentNoteStateEvent.DoesNotExist:
            return False
        return bool(state.state != NoteStates.LOCKED)

    def visible(self) -> bool:
        """Show the button only when enabled and the note is still open."""
        note_dbid = self.event.context.get("note_id")
        if not note_dbid or not self._enabled():
            return False
        return self._note_is_open(note_dbid)

    def handle(self) -> list[Effect]:
        """Return a review effect for each staged prescription that is not a controlled compound."""
        note_dbid = self.event.context.get("note_id")
        if not note_dbid or not self._enabled() or not self._note_is_open(note_dbid):
            log.warning(
                "Review all prescriptions: button pressed while hidden, ignoring"
            )
            return []

        commands = list(
            Command.objects.filter(
                note__dbid=note_dbid,
                state=STAGED,
                schema_key__in=list(REVIEWABLE_COMMANDS),
                entered_in_error__isnull=True,
            ).order_by("dbid")
        )
        controlled_compounds = self._controlled_compound_dbids(commands)

        effects: list[Effect] = []
        for command in commands:
            if self._compound_dbids(command) & controlled_compounds:
                log.info(
                    f"Skipping command {command.id}: controlled or unknown compound"
                )
                continue
            command_class = REVIEWABLE_COMMANDS[command.schema_key]
            effects.append(command_class(command_uuid=str(command.id)).review())
            log.info(
                f"Review effect added for {command.schema_key} command {command.id}"
            )
        return effects

    @staticmethod
    def _compound_dbids(command: Command) -> set[int]:
        """Return the compound medication dbids the command prescribes, if any.

        A compound whose id cannot be read is returned as -1 so it is treated as controlled.
        """
        data = command.data if isinstance(command.data, dict) else {}
        dbids: set[int] = set()
        for field in MEDICATION_FIELDS:
            medication = data.get(field)
            if not isinstance(medication, dict):
                continue
            extra = medication.get("extra")
            if (
                not isinstance(extra, dict)
                or extra.get("is_compound_medication") is not True
            ):
                continue
            value = medication.get("value")
            dbids.add(value if isinstance(value, int) else -1)
        return dbids

    def _controlled_compound_dbids(self, commands: list[Command]) -> set[int]:
        """Compound dbids that must be skipped: scheduled, or not found (fail closed)."""
        compound_dbids: set[int] = set()
        for command in commands:
            compound_dbids |= self._compound_dbids(command)
        if not compound_dbids:
            return set()
        not_controlled = set(
            CompoundMedication.objects.filter(
                dbid__in=compound_dbids, controlled_substance=NOT_CONTROLLED
            ).values_list("dbid", flat=True)
        )
        return compound_dbids - not_controlled
