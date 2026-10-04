"""Marks the recheck booked or unbooked on every active enrolment of a patient.

This is a freshness improvement rather than a correctness requirement. The daily walk
evaluates the same function on the morning a conditional step is due, so a patient who
books between two walks is still never chased.
"""

from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler
from canvas_sdk.v1.data import Appointment

from medication_followup_protocol.models import Enrollment, EnrollmentStatus
from medication_followup_protocol.services.recheck import booked_recheck


class AppointmentWatcher(BaseHandler):
    """Reevaluate the recheck when an appointment is created, cancelled or moved."""

    RESPONDS_TO = [
        EventType.Name(EventType.APPOINTMENT_CREATED),
        EventType.Name(EventType.APPOINTMENT_CANCELED),
        EventType.Name(EventType.APPOINTMENT_RESCHEDULED),
    ]

    def compute(self) -> list[Effect]:
        """Store or clear the recheck appointment on each active enrolment."""
        appointment = Appointment.objects.filter(id=self.event.target.id).first()
        if appointment is None or appointment.patient_id is None:
            return []

        enrollments = Enrollment.objects.filter(
            status=EnrollmentStatus.ACTIVE,
            patient__dbid=appointment.patient_id,
        )
        for enrollment in enrollments:
            recheck = booked_recheck(enrollment)
            enrollment.recheck_booked_appointment_id = str(recheck.id) if recheck else None
            enrollment.save()

        # Nothing is emitted. The state this writes is read by the walk rather than shown.
        return []
