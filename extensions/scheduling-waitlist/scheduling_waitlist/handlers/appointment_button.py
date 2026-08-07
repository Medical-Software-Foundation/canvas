"""Add-to-waitlist button on a cancelled or no-showed appointment.

The scheduling spec asks for this button "from a cancelled/declined
appointment". Canvas offers no button surface on the calendar grid or an
appointment card, but every appointment has a note, and notes do have button
surfaces. So the button lives on the note header and shows itself only while
that note is in a cancelled or no-show state.

Because the appointment is in hand, the form arrives pre-filled with the
service, provider, and location of the slot that just freed up -- which is the
whole reason a scheduler wants the button here.
"""

from __future__ import annotations

from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data import Appointment, Note
from canvas_sdk.v1.data.note import NoteStates

from scheduling_waitlist.constants import PREFERENCE_SPECIFIC
from scheduling_waitlist.services.config import WaitlistConfig
from scheduling_waitlist.services.display import note_type_name
from scheduling_waitlist.services.form import build_form_context

# The states that mean a booked slot has been given up.
FREED_STATES = (NoteStates.CANCELLED, NoteStates.NOSHOW)


class AddToWaitlistAppointmentButton(ActionButton):
    """Offers the waitlist form from an appointment that has just freed up."""

    BUTTON_KEY = "scheduling_waitlist_add_from_appointment"
    BUTTON_TITLE = "Add to waitlist"
    BUTTON_LOCATION = ActionButton.ButtonLocation.NOTE_HEADER

    # -- context ---------------------------------------------------------

    def _note_dbid(self) -> Any | None:
        return self.context.get("note_id")

    def _note_state(self) -> str:
        """Current state of the note this button is rendered on."""
        note_dbid = self._note_dbid()
        if not note_dbid:
            return ""
        note = Note.objects.filter(dbid=note_dbid).first()
        if note is None:
            return ""
        current = getattr(note, "current_state", None)
        return getattr(current, "state", "") or ""

    def _appointment(self) -> Any | None:
        note_dbid = self._note_dbid()
        if not note_dbid:
            return None
        return (
            Appointment.objects.filter(note__dbid=note_dbid, entered_in_error__isnull=True)
            .select_related("patient", "note_type", "provider", "location")
            .first()
        )

    # -- behavior --------------------------------------------------------

    def visible(self) -> bool:
        """Only on an appointment note whose slot has been given up.

        Everywhere else this button would be noise, and adding a patient to the
        waitlist for an appointment they are about to attend makes no sense.
        """
        return self._note_state() in FREED_STATES

    def handle(self) -> list[Effect]:
        """Render the form, pre-filled from the freed slot."""
        appointment = self._appointment()
        if appointment is None:
            return []

        patient = getattr(appointment, "patient", None)
        if patient is None:
            return []

        prefill: dict[str, Any] = {}
        if getattr(appointment, "note_type_id", None):
            prefill["appointment_type_id"] = appointment.note_type_id
        if getattr(appointment, "provider_id", None):
            prefill["provider_id"] = appointment.provider_id
            prefill["provider_preference"] = PREFERENCE_SPECIFIC
        if getattr(appointment, "location_id", None):
            prefill["location_id"] = appointment.location_id
            prefill["location_preference"] = PREFERENCE_SPECIFIC

        context = build_form_context(
            patient=patient,
            config=WaitlistConfig.from_secrets(self.secrets),
            prefill=prefill,
            heading="Add to waitlist",
            intro=f"pre-filled from this {note_type_name(getattr(appointment, 'note_type', None))}",
        )
        html = render_to_string("templates/add_to_waitlist.html", context)

        return [
            LaunchModalEffect(
                content=html,
                target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE,
                title="Add to waitlist",
            ).apply()
        ]
