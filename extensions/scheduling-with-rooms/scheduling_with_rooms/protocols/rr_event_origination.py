"""Create the RR room ScheduleEvent for a freshly-created Appointment.

The /book endpoint stashes the room booking intent in the cache, keyed by
(patient_id, provider_id, start_time_utc). When Canvas creates the
Appointment, this handler pops the intent and creates a ScheduleEvent on
the RR staff member's calendar with ``parent_appointment_id`` pointing at
the patient Appointment, so the cascade handler can find the room event
via the children relationship instead of via FHIR.
"""

from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.effects.note.appointment import ScheduleEvent
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.v1.data.appointment import Appointment
from logger import log

from scheduling_with_rooms.utils.rr_event_cache import pop as pop_rr_event


class RREventOrigination(BaseProtocol):
    """On APPOINTMENT_CREATED, create the linked room ScheduleEvent."""

    RESPONDS_TO = EventType.Name(EventType.APPOINTMENT_CREATED)

    def compute(self) -> list[Effect]:
        appointment_id = self.target
        try:
            appointment = (
                Appointment.objects
                .select_related("patient", "provider")
                .get(id=appointment_id)
            )
        except Appointment.DoesNotExist:
            log.warning("rr-event: appointment %s not found", appointment_id)
            return []

        patient_uuid = str(appointment.patient.id) if appointment.patient else ""
        provider_uuid = str(appointment.provider.id) if appointment.provider else ""
        if not appointment.start_time or not patient_uuid or not provider_uuid:
            return []

        intent = pop_rr_event(patient_uuid, provider_uuid, appointment.start_time)
        if not intent:
            return []

        kwargs = {
            "note_type_id": intent["note_type_id"],
            "patient_id": patient_uuid,
            "start_time": appointment.start_time,
            "duration_minutes": int(intent["duration_minutes"]),
            "practice_location_id": intent["location_id"],
            "provider_id": intent["rr_staff_id"],
            "parent_appointment_id": str(appointment.id),
        }
        if intent.get("description"):
            kwargs["description"] = intent["description"]

        log.info(
            "rr-event: creating ScheduleEvent for appointment %s on rr_staff=%s",
            appointment.id, intent["rr_staff_id"],
        )
        return [ScheduleEvent(**kwargs).create()]
