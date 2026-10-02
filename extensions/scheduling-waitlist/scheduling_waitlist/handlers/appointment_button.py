"""Add-to-waitlist from the appointment that just freed up.

The moment a slot is given up is the moment a scheduler knows someone wants it,
and the patient who gave it up often wants a different time rather than nothing at
all. So the button belongs where that happened.

Canvas offers no button surface on the calendar grid or an appointment card, but
every appointment has a note and notes do have one. The button therefore lives on
the note header and shows itself only while that appointment is cancelled or
no-showed -- inviting a waitlist entry for a visit somebody is about to attend
would be noise.

In practice that reaches the **no-show** only, and the shortfall is the platform's
rather than this handler's. Cancelling an appointment tombstones its note: the
timeline shows a greyed strip with a ``Restore`` link and nothing else, and the note
never opens. All four note button locations -- header, footer, body, header dropdown
-- need an open note, and the SDK has no appointment, calendar or timeline location
at all, so there is nowhere for a plugin to draw. The condition below is correct;
what is missing is a surface.

Do not "fix" that by widening the condition or moving the location -- the condition
already admits cancellations, and every location the SDK defines is listed above as
unavailable. A patient who has just cancelled is added from the chart-header button
instead, which costs only the pre-fill. The README's maintainer notes carry the full
reasoning and the follow-up worth doing if the manual re-entry proves annoying.

Because the appointment is in hand, the form opens pre-filled with the service,
provider and location of the slot that just freed up, which is the whole reason
to offer the button here rather than making the scheduler re-enter it.
"""

from __future__ import annotations

from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.v1.data import Appointment
from canvas_sdk.v1.data.appointment import AppointmentProgressStatus
from canvas_sdk.v1.data.note import NoteStates

from scheduling_waitlist.constants import (
    BUTTON_ADD_TITLE,
    BUTTON_LISTED_TITLE,
    LISTED_BUTTON_BACKGROUND,
    LISTED_BUTTON_TEXT,
    ROSTER_URL,
    add_form_url,
    edit_form_url,
)
from scheduling_waitlist.services.entries import (
    find_live_entry,
    has_live_entry_for_service,
)

ADD_MODAL_TITLE = "Add to waitlist"
EDIT_MODAL_TITLE = "Edit waitlist entry"
LISTED_MODAL_TITLE = "Scheduling Waitlist"

# A slot can be given up in two records, and only one of them is certain to move.
#
# Marking no-show in the UI is a note state transition -- a NoteStateChangeEvent,
# surfaced by the CurrentNoteStateEvent view. Whether the platform also writes
# Appointment.status is server behaviour a plugin cannot see. Reading only the
# status field meant the button never appeared after a no-show, so both are
# consulted and either is enough.
FREED_STATUSES = frozenset(
    {
        str(AppointmentProgressStatus.CANCELLED),
        str(AppointmentProgressStatus.NOSHOWED),
    }
)

FREED_NOTE_STATES = frozenset({str(NoteStates.CANCELLED), str(NoteStates.NOSHOW)})

# ``note__current_state`` is selected so the note's state costs no second query.
RELATED = ("patient", "note_type", "provider", "location", "note__current_state")


class AddToWaitlistAppointmentButton(ActionButton):
    """Offers the waitlist form from an appointment that has just freed up."""

    BUTTON_TITLE = BUTTON_ADD_TITLE
    BUTTON_KEY = "scheduling_waitlist__add_from_appointment"
    BUTTON_LOCATION = ActionButton.ButtonLocation.NOTE_HEADER

    def _note_dbid(self) -> Any | None:
        """The note this button is rendered on.

        A note-header button receives the note's *dbid* -- a small integer, not a
        UUID -- and the platform puts it on both the context and the target, so
        both are read.
        """
        context = getattr(self.event, "context", None) or {}
        return context.get("note_id") or getattr(
            getattr(self.event, "target", None), "id", None
        )

    def _appointment(self) -> Any | None:
        """The appointment behind this note, if there is one."""
        note_dbid = self._note_dbid()
        if not note_dbid:
            return None
        return (
            Appointment.objects.filter(
                note__dbid=note_dbid, entered_in_error__isnull=True
            )
            .select_related(*RELATED)
            .first()
        )

    @staticmethod
    def _note_state(appointment: Any) -> str:
        """The current state of this appointment's note, if it has one.

        Walked defensively: an appointment may carry no note, and a note may have
        no state history yet, either of which leaves nothing to read.
        """
        note = getattr(appointment, "note", None)
        current = getattr(note, "current_state", None)
        return str(getattr(current, "state", "") or "")

    @staticmethod
    def _already_waiting(appointment: Any) -> bool:
        """Whether this patient already wants the service that just freed up.

        Deliberately scoped to this slot's service rather than to the waitlist as
        a whole: somebody waiting for a physical is not waiting for the follow-up
        that just opened, and saying "On waitlist" there would talk a scheduler
        out of adding the very thing they should.

        A slot with no service cannot answer the question, so it reads as not
        waiting -- the form it opens has no service to pre-fill either.
        """
        patient = getattr(appointment, "patient", None)
        return has_live_entry_for_service(
            getattr(patient, "dbid", None), getattr(appointment, "note_type_id", None)
        )

    def visible(self) -> bool:
        """Only on an appointment note whose slot has been given up.

        Everywhere else -- a regular office note, a booked appointment -- this
        button would be clutter.

        Either record counts as given up. See ``FREED_STATUSES`` above: only one
        of the two is guaranteed to move, and which one is not knowable here.

        The label is decided here too, because the platform reads
        ``BUTTON_TITLE`` immediately after this returns. Assigned to ``self``
        rather than the class: a class attribute would carry one note's label
        onto the next.
        """
        appointment = self._appointment()
        if appointment is None:
            return False
        if getattr(appointment, "patient", None) is None:
            # A waitlist entry needs somebody to put on it.
            return False

        status = str(getattr(appointment, "status", "") or "")
        if status not in FREED_STATUSES and self._note_state(appointment) not in FREED_NOTE_STATES:
            return False

        waiting = self._already_waiting(appointment)
        self.BUTTON_TITLE = BUTTON_LISTED_TITLE if waiting else BUTTON_ADD_TITLE
        # Matches the chart-header button rather than styling this surface
        # separately: the same two states mean the same two things wherever they
        # are drawn, and a note header is the surface reviewers found ambiguous.
        self.BUTTON_BACKGROUND_COLOR = LISTED_BUTTON_BACKGROUND if waiting else None
        self.BUTTON_TEXT_COLOR = LISTED_BUTTON_TEXT if waiting else None
        return True

    def handle(self) -> list[Effect]:
        """Open whichever surface the label promised.

        "Waitlist" opens the compact form pre-filled from the freed slot -- this
        is the one surface where a form still earns its place, because the slot
        already knows the service, provider and location, and pre-filling them is
        the whole reason to offer a button here rather than on the chart, which
        writes immediately. "On waitlist" opens the roster instead, the same as the
        chart-header button does: offering an add form for a service they are
        already waiting for would only earn a 409 from the duplicate guard.
        Instead it opens that entry's own compact form, so the want they already
        stated can be changed while the freed slot is in front of them -- the same
        thing the chart-header button's "On waitlist" does. Two buttons with one
        label behaving two ways would be a defect, whichever way each behaved.

        Which entry is not a guess here: ``visible()`` only says "On waitlist" for
        a live entry matching *this slot's service*, so there is exactly one to
        open. It falls back to the roster if that entry has gone between the
        render and the click.

        The lookups are repeated rather than carried over from ``visible()``,
        which is a separate invocation with no state to reuse.
        """
        appointment = self._appointment()
        if appointment is None:
            return []

        patient = getattr(appointment, "patient", None)
        patient_id = getattr(patient, "id", None)
        if not patient_id:
            return []

        # Gated on ``_already_waiting`` rather than on ``find_live_entry`` alone,
        # which would be one query fewer. A slot with no service reads as "not
        # waiting" there, whereas ``find_live_entry(dbid, None)`` would filter on
        # a null service and match the *general* entries a quick add creates --
        # turning "add for this slot" into "edit something else". The extra query
        # happens only on a click, never on a render.
        if self._already_waiting(appointment):
            entry = find_live_entry(
                getattr(patient, "dbid", None),
                getattr(appointment, "note_type_id", None),
            )
            if entry is None:
                url, title = ROSTER_URL, LISTED_MODAL_TITLE
            else:
                url, title = (
                    edit_form_url(getattr(entry, "dbid", None)),
                    EDIT_MODAL_TITLE,
                )
        else:
            url, title = (
                add_form_url(
                    str(patient_id),
                    note_type_dbid=getattr(appointment, "note_type_id", None),
                    provider_dbid=getattr(appointment, "provider_id", None),
                    location_dbid=getattr(appointment, "location_id", None),
                ),
                ADD_MODAL_TITLE,
            )

        return [
            LaunchModalEffect(
                url=url,
                target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
                title=title,
            ).apply()
        ]
