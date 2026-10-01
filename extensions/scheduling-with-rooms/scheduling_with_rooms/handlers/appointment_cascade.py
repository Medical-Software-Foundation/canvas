"""Cascade APPOINTMENT_CANCELED to the room ScheduleEvent a visit holds.

When a patient appointment is cancelled, delete the room event it holds so the
room is released rather than left blocked against nothing.

Finding that event is not simply ``appointment.children``. That reverse FK is
set at create and nulled by ``ScheduleEvent.reschedule()``, which the reschedule
flow uses — so a visit that has ever been rescheduled has no children and its
room would be held forever. ``room_link.find_room_events`` handles both cases;
it's shared with the reschedule path so the two agree.

This handler does not need to guard against firing mid-reschedule: Canvas emits
APPOINTMENT_UPDATED, not APPOINTMENT_CANCELED, for the appointment a reschedule
supersedes (verified against bigleaphealth-dev logs, 2026-07-31).
"""

from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.effects.note.appointment import ScheduleEvent
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data.appointment import Appointment
from logger import log

from scheduling_with_rooms.utils.room_link import find_room_events


class AppointmentCascadeHandler(BaseHandler):
    """Release the room when a patient appointment is cancelled."""

    RESPONDS_TO = EventType.Name(EventType.APPOINTMENT_CANCELED)

    def compute(self) -> list[Effect]:
        appointment_id = self.target
        log.info("cascade: APPOINTMENT_CANCELED for %s", appointment_id)

        try:
            appointment = (
                Appointment.objects
                .select_related("note", "patient")
                .prefetch_related("children__note_type")
                .get(id=appointment_id)
            )
        except Appointment.DoesNotExist:
            log.warning("cascade: appointment %s not found", appointment_id)
            return []

        room_events = find_room_events(appointment)
        if not room_events:
            log.info("cascade: no room event for appointment %s", appointment_id)
            return []

        effects: list[Effect] = []
        for event in room_events:
            log.info(
                "cascade: deleting room ScheduleEvent %s for cancelled appointment %s",
                event.id, appointment_id,
            )
            effects.append(ScheduleEvent(instance_id=str(event.id)).delete())
        return effects
