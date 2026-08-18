"""Add-to-waitlist from the appointment that just freed up.

The moment a slot is given up is the moment a scheduler knows someone wants it,
and the patient who cancelled often wants a different time rather than nothing at
all. So the button belongs where the cancellation happened.

Canvas offers no button surface on the calendar grid or an appointment card, but
every appointment has a note and notes do have one. The button therefore lives on
the note header and shows itself only while that appointment is cancelled or
no-showed -- inviting a waitlist entry for a visit somebody is about to attend
would be noise.

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

from scheduling_waitlist.constants import add_form_url

BUTTON_TITLE = "Add to waitlist"
MODAL_TITLE = "Add to waitlist"

# The statuses that mean a booked slot has been given up. Read from the
# appointment rather than from the note's state history: it is one field, and it
# is the same field the freed-slot handler reacts to.
FREED_STATUSES = frozenset(
    {
        str(AppointmentProgressStatus.CANCELLED),
        str(AppointmentProgressStatus.NOSHOWED),
    }
)

RELATED = ("patient", "note_type", "provider", "location")


class AddToWaitlistAppointmentButton(ActionButton):
    """Offers the waitlist form from an appointment that has just freed up."""

    BUTTON_TITLE = BUTTON_TITLE
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

    def visible(self) -> bool:
        """Only on an appointment note whose slot has been given up.

        Everywhere else -- a regular office note, a booked appointment -- this
        button would be clutter.
        """
        appointment = self._appointment()
        if appointment is None:
            return False
        if getattr(appointment, "patient", None) is None:
            # A waitlist entry needs somebody to put on it.
            return False
        return str(getattr(appointment, "status", "") or "") in FREED_STATUSES

    def handle(self) -> list[Effect]:
        """Open the compact add form, pre-filled from the freed slot."""
        appointment = self._appointment()
        if appointment is None:
            return []

        patient = getattr(appointment, "patient", None)
        patient_id = getattr(patient, "id", None)
        if not patient_id:
            return []

        return [
            LaunchModalEffect(
                url=add_form_url(
                    str(patient_id),
                    note_type_dbid=getattr(appointment, "note_type_id", None),
                    provider_dbid=getattr(appointment, "provider_id", None),
                    location_dbid=getattr(appointment, "location_id", None),
                ),
                target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
                title=MODAL_TITLE,
            ).apply()
        ]
