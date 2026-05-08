"""Cascade APPOINTMENT_CANCELED to the linked RR room ScheduleEvent.

When a patient appointment is cancelled, walk its ``children`` (the
``ScheduleEvent`` rows the booking flow created with
``parent_appointment_id`` pointing at this appointment) and delete any
non-cancelled schedule_event-typed children. Reschedules go through the
plugin's /book endpoint, which creates a fresh ScheduleEvent linked to
the new appointment, so this handler does not need a reschedule branch.
"""

from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.effects.note.appointment import ScheduleEvent
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.v1.data.appointment import Appointment, AppointmentProgressStatus
from canvas_sdk.v1.data.note import NoteTypeCategories
from logger import log


class AppointmentCascadeHandler(BaseProtocol):
    """Cancel the linked RR room ScheduleEvent when a patient appointment is cancelled."""

    RESPONDS_TO = EventType.Name(EventType.APPOINTMENT_CANCELED)

    def compute(self) -> list[Effect]:
        appointment_id = self.target
        log.info("cascade: APPOINTMENT_CANCELED for %s", appointment_id)

        try:
            appointment = (
                Appointment.objects
                .prefetch_related("children__note_type")
                .get(id=appointment_id)
            )
        except Appointment.DoesNotExist:
            log.warning("cascade: appointment %s not found", appointment_id)
            return []

        rr_children = [
            child for child in appointment.children.all()
            if child.note_type
            and child.note_type.category == NoteTypeCategories.SCHEDULE_EVENT
            and child.status != AppointmentProgressStatus.CANCELLED
        ]
        if not rr_children:
            log.info("cascade: no RR children for appointment %s", appointment_id)
            return []

        effects: list[Effect] = []
        for child in rr_children:
            log.info(
                "cascade: deleting RR ScheduleEvent %s (parent=%s)",
                child.id, appointment_id,
            )
            effects.append(ScheduleEvent(instance_id=str(child.id)).delete())
        return effects
