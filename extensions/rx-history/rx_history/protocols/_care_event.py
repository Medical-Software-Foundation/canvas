from datetime import date, timedelta
from typing import Iterable

from canvas_sdk.v1.data.appointment import Appointment, AppointmentProgressStatus

CARE_EVENT_WINDOW_DAYS = 7


def has_care_event_within(patient_id: str, days: int = CARE_EVENT_WINDOW_DAYS) -> bool:
    """Return True when the patient has a non cancelled appointment within the window."""
    today = date.today()
    window_end = today + timedelta(days=days)
    return bool(
        Appointment.objects.filter(
            patient__id=patient_id,
            start_time__date__gte=today,
            start_time__date__lte=window_end,
        )
        .exclude(
            status__in=[
                AppointmentProgressStatus.CANCELLED,
                AppointmentProgressStatus.NOSHOWED,
            ]
        )
        .exists()
    )


def partition_by_care_event(
    patient_ids: Iterable[str], days: int = CARE_EVENT_WINDOW_DAYS
) -> tuple[list[str], list[str]]:
    """Split patient ids into those with and without a care event in the window."""
    patient_ids = list(patient_ids)
    if not patient_ids:
        return [], []
    today = date.today()
    window_end = today + timedelta(days=days)
    qualifying = {
        str(pid)
        for pid in Appointment.objects.filter(
            patient__id__in=patient_ids,
            start_time__date__gte=today,
            start_time__date__lte=window_end,
        )
        .exclude(
            status__in=[
                AppointmentProgressStatus.CANCELLED,
                AppointmentProgressStatus.NOSHOWED,
            ]
        )
        .values_list("patient__id", flat=True)
    }
    allowed = [pid for pid in patient_ids if str(pid) in qualifying]
    blocked = [pid for pid in patient_ids if str(pid) not in qualifying]
    return allowed, blocked
