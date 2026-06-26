"""Expand a recurring appointment into its linked series.

Fires after an appointment is created. The booking flow stamps the recurrence
rule onto the series *parent* as a ``RECURRENCE_SYSTEM`` external identifier;
children are created without it, so they fall through here (no recursion). Each
child links to the parent via ``parent_appointment_id`` — giving the series
home-app's native cancel/reschedule-following cascade. The parent's reason for
visit is replicated onto each child's note so the whole series carries it.
"""

from __future__ import annotations

from uuid import uuid4

from canvas_sdk.effects import Effect
from canvas_sdk.effects.note.appointment import Appointment
from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler
from canvas_sdk.v1.data.appointment import Appointment as AppointmentModel
from scheduling_app.booking import _rfv_command
from scheduling_app.recurrence import (
    RECURRENCE_SYSTEM,
    RFV_SYSTEM,
    decode_recurrence,
    decode_rfv,
    occurrence_start_times,
)


class AppointmentRecurrence(BaseHandler):
    """Create the child appointments for a recurring series parent."""

    RESPONDS_TO = EventType.Name(EventType.APPOINTMENT_CREATED)

    def compute(self) -> list[Effect]:
        """Read the parent's recurrence rule and emit one CREATE per occurrence."""
        appointment = (
            AppointmentModel.objects.filter(id=self.event.target.id)
            .select_related("patient", "provider", "location", "note_type")
            .first()
        )
        if appointment is None:
            return []
        # Only series parents carry the recurrence identifier; children (created
        # below, without it) and non-recurring appointments fall through.
        identifier = appointment.external_identifiers.filter(system=RECURRENCE_SYSTEM).first()
        if identifier is None:
            return []
        if not (
            appointment.patient and appointment.provider and appointment.location and appointment.note_type
        ):
            return []

        recurrence = decode_recurrence(identifier.value)
        if recurrence is None:
            return []

        # Replicate the parent's reason for visit onto each child's note. The RFV
        # is read from the parent's external identifier (written atomically with
        # the parent) rather than its note command — the note command is created
        # by a separate, async effect that can race this handler. Children are
        # created with a known instance_id so the RFV command can target their note.
        rfv_identifier = appointment.external_identifiers.filter(system=RFV_SYSTEM).first()
        rfv_visit = decode_rfv(rfv_identifier.value) if rfv_identifier else None
        effects: list[Effect] = []
        for start_time in occurrence_start_times(appointment.start_time, recurrence):
            child_id = str(uuid4())
            effects.append(
                Appointment(
                    instance_id=child_id,
                    patient_id=appointment.patient.id,
                    parent_appointment_id=appointment.id,
                    start_time=start_time,
                    duration_minutes=appointment.duration_minutes,
                    provider_id=appointment.provider.id,
                    practice_location_id=appointment.location.id,
                    meeting_link=appointment.meeting_link,
                    appointment_note_type_id=appointment.note_type.id,
                ).create()
            )
            if rfv_visit and (command := _rfv_command(rfv_visit, note_uuid=child_id)):
                effects.append(command.originate())
        return effects
