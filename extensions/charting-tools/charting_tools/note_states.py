"""Which notes are still open for charting."""

from canvas_sdk.v1.data.note import CurrentNoteStateEvent, NoteStates

# Open for charting, or a booked visit. Canvas's own "editable" set leaves out
# booked notes, but a visit's template and rules go in at booking.
OPEN_NOTE_STATES = (
    NoteStates.NEW,
    NoteStates.SCHEDULING,
    NoteStates.BOOKED,
    NoteStates.CONVERTED,
    NoteStates.PUSHED,
    NoteStates.UNLOCKED,
    NoteStates.RESTORED,
    NoteStates.UNDELETED,
)


def note_is_open(note_dbid: int) -> bool:
    """Whether the note's current state is one commands can still be added in."""
    return bool(CurrentNoteStateEvent.objects.filter(note_id=note_dbid, state__in=OPEN_NOTE_STATES).exists())
