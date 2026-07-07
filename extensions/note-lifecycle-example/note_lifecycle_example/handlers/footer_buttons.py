from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.handlers.action_button import (
    LockNoteActionButton,
    NoteStateActionButton,
    SignNoteActionButton,
)
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.note import Note, NoteStates, NoteTypeCategories

_WHITE = "#ffffff"
_GREEN = "#21ba45"


def _note_type_info(note_id: int | str | None) -> tuple[str, bool] | None:
    """Return the context note's (category, is_sig_required), or None if there is no note."""
    if not note_id:
        return None

    info: tuple[str, bool] | None = (
        Note.objects.filter(dbid=note_id)
        .values_list(
            "note_type_version__category", "note_type_version__is_sig_required"
        )
        .first()
    )
    return info


class LockNoteButton(LockNoteActionButton):
    """Lock the current note (shown only for note types that don't require a signature)."""

    BUTTON_TEXT_COLOR = _WHITE
    BUTTON_BACKGROUND_COLOR = _GREEN


class SignNoteButton(SignNoteActionButton):
    """Sign the current note.

    Also hidden while the note still has staged (uncommitted) commands — a note can't be
    signed until its commands are committed. ``ReloadFooterOnCommandCommit`` reloads the
    footer on each command commit, so the button reappears once the last command is
    committed. (The lock-first, sig-required and already-signed rules come from
    ``SignNoteActionButton``.)
    """

    BUTTON_TEXT_COLOR = _WHITE
    BUTTON_BACKGROUND_COLOR = _GREEN

    def visible(self) -> bool:
        """Show only when the transition is allowed and no command is left uncommitted."""
        if not super().visible():
            return False
        note_id = self.event.context.get("note_id")
        return (
            not Command.objects.filter(note_id=note_id, state="staged")
            .exclude(schema_key="reasonForVisit")
            .exists()
        )


class UnlockNoteButton(NoteStateActionButton):
    """Unlock the current note (titled "Amend" for signature-required note types)."""

    STATE_ACTION = NoteStates.UNLOCKED
    BUTTON_TEXT_COLOR = _WHITE
    BUTTON_BACKGROUND_COLOR = _GREEN

    def compute(self) -> list[Effect]:
        """Title the button "Amend" when the note type requires a signature."""
        info = _note_type_info(self.event.context.get("note_id"))
        if info is not None and info[1]:
            self.BUTTON_TITLE = "Amend"
        effects: list[Effect] = super().compute()
        return effects


class PushChargesNoteButton(NoteStateActionButton):
    """Push charges for the current note."""

    STATE_ACTION = NoteStates.PUSHED


class CheckInAppointmentButton(NoteStateActionButton):
    """Check in the current appointment note."""

    STATE_ACTION = NoteStates.CONVERTED
    BUTTON_TITLE = "Check in"
    BUTTON_BACKGROUND_COLOR = _GREEN
    BUTTON_TEXT_COLOR = _WHITE


class NoShowAppointmentButton(NoteStateActionButton):
    """Mark the current appointment note as a no-show."""

    STATE_ACTION = NoteStates.NOSHOW


class CancelAppointmentButton(NoteStateActionButton):
    """Cancel the current appointment note."""

    STATE_ACTION = NoteStates.CANCELLED


class RestoreAppointmentButton(NoteStateActionButton):
    """Restore (revert) the current cancelled appointment note."""

    STATE_ACTION = NoteStates.REVERTED


class DeleteNoteButton(NoteStateActionButton):
    """Delete the current note."""

    STATE_ACTION = NoteStates.DELETED


class RestoreNoteButton(NoteStateActionButton):
    """Restore the current (deleted) note."""

    STATE_ACTION = NoteStates.UNDELETED


class DischargeNoteButton(NoteStateActionButton):
    """Discharge the current note."""

    STATE_ACTION = NoteStates.DISCHARGED

    def visible(self) -> bool:
        """Show only for inpatient note types, matching the native footer."""
        info = _note_type_info(self.event.context.get("note_id"))
        return (
            super().visible()
            and info is not None
            and info[0] == NoteTypeCategories.INPATIENT
        )
