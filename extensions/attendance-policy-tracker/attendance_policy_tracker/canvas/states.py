"""Canvas note state vocabulary, kept in one place.

This is the seam. The counting core is deliberately free of Canvas vocabulary and
takes the state strings as arguments, so every stored value Canvas uses appears
here and nowhere else. Changing what Canvas calls a cancellation is a change to
this file only.
"""

from canvas_sdk.v1.data.note import NoteStates

# A visit the patient did not attend. The enum attribute is one word with no
# underscore, and the stored value is three characters.
NO_SHOW_STATES = (NoteStates.NOSHOW.value,)

# A visit that was cancelled. Note the attribute carries two Ls while the human
# label Canvas shows carries one.
CANCELLED_STATES = (NoteStates.CANCELLED.value,)

# A booking. A reschedule writes one of these rather than a cancellation, which
# is why a moved visit cannot be read as a cancellation from the history.
BOOKED_STATES = (NoteStates.BOOKED.value,)

# Scheduling, written when a visit is first placed on the calendar.
SCHEDULING_STATES = (NoteStates.SCHEDULING.value,)

# A reversal, written by the Restore action Canvas offers on a cancelled or a no
# show note. It undoes a cancellation and a no show alike, so both detectors
# treat it the same way. The enum also carries a RESTORED state, but that one is
# vestigial and the platform never writes it, so it has no place here.
REVERTED_STATES = (NoteStates.REVERTED.value,)
