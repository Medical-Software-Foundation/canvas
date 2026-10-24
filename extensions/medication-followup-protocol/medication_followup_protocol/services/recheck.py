"""The single definition of whether a recheck is booked.

Both the daily walk and the appointment watcher ask this question and neither answers it
for itself, so a change to what counts as a booked recheck changes one function.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canvas_sdk.v1.data import Appointment
from canvas_sdk.v1.data.appointment import AppointmentProgressStatus

if TYPE_CHECKING:
    from medication_followup_protocol.models import Enrollment


def booked_recheck(enrollment: "Enrollment") -> Appointment | None:
    """The recheck appointment for this enrolment, or None when none is booked.

    A recheck exists when the patient has an appointment of the enrolment's recheck note
    type, starting after the enrolment start date, that is not cancelled.
    """
    if not enrollment.recheck_note_type_id:
        return None

    return (
        Appointment.objects.filter(
            patient__dbid=enrollment.patient_id,
            note_type__id=enrollment.recheck_note_type_id,
            start_time__date__gt=enrollment.start_date,
        )
        .exclude(status=AppointmentProgressStatus.CANCELLED)
        .order_by("start_time")
        .first()
    )


def is_recheck_booked(enrollment: "Enrollment") -> bool:
    """Whether a recheck is booked for this enrolment."""
    return booked_recheck(enrollment) is not None
