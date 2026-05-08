"""Cascade appointment cancellation/rescheduling to RR staff ScheduleEvents.

When a patient appointment is cancelled (or cancelled as part of a reschedule),
this handler finds any matching RR staff ScheduleEvent created at the same time
for the same patient and cancels (or reschedules) it accordingly.
"""

from __future__ import annotations

import datetime
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.note.appointment import ScheduleEvent
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.v1.data.appointment import Appointment
from canvas_sdk.v1.data.staff import Staff
from logger import log

from scheduling_with_rooms.utils.fhir_client import FHIRClient


class AppointmentCascadeHandler(BaseProtocol):
    """Cancel or reschedule RR staff ScheduleEvents when an appointment is cancelled."""

    RESPONDS_TO = EventType.Name(EventType.APPOINTMENT_CANCELED)

    def compute(self) -> list[Effect]:
        appointment_id = self.target
        log.info("cascade: APPOINTMENT_CANCELED for %s", appointment_id)

        try:
            appointment = Appointment.objects.get(id=appointment_id)
        except Appointment.DoesNotExist:
            log.warning("cascade: appointment %s not found", appointment_id)
            return []

        patient_id = str(appointment.patient_id) if appointment.patient_id else ""
        if not patient_id or not appointment.start_time:
            log.info("cascade: no patient_id or start_time, skipping")
            return []

        # Identify active RR staff.
        rr_staff_ids = {
            str(sid)
            for sid in Staff.objects.filter(
                active=True, roles__internal_code="RR",
            ).values_list("id", flat=True)
        }
        if not rr_staff_ids:
            log.info("cascade: no active RR staff, skipping")
            return []

        fhir = FHIRClient(self.secrets)

        # Find RR ScheduleEvents matching this appointment's patient + time.
        rr_events = _find_matching_rr_events(
            fhir, patient_id, appointment.start_time, rr_staff_ids,
        )
        if not rr_events:
            log.info(
                "cascade: no matching RR events for appointment %s", appointment_id,
            )
            return []

        # Check if this cancellation is part of a reschedule: look for a new
        # appointment that was rescheduled from the cancelled one.
        new_appt = Appointment.objects.filter(
            appointment_rescheduled_from=appointment,
        ).first()

        effects: list[Effect] = []

        for rr_event_id in rr_events:
            if new_appt and new_appt.start_time:
                se = ScheduleEvent(instance_id=rr_event_id)
                se.start_time = new_appt.start_time
                se.duration_minutes = (
                    new_appt.duration_minutes or appointment.duration_minutes
                )
                result = se.reschedule()
                if isinstance(result, list):
                    effects.extend(result)
                else:
                    effects.append(result)
                log.info(
                    "cascade: rescheduling RR event %s to %s",
                    rr_event_id,
                    new_appt.start_time.isoformat(),
                )
            else:
                se = ScheduleEvent(instance_id=rr_event_id)
                result = se.delete()
                if isinstance(result, list):
                    effects.extend(result)
                else:
                    effects.append(result)
                log.info("cascade: cancelling RR event %s", rr_event_id)

        return effects


def _find_matching_rr_events(
    fhir: FHIRClient,
    patient_id: str,
    appointment_start: datetime.datetime,
    rr_staff_ids: set[str],
) -> list[str]:
    """Return FHIR appointment IDs for RR staff matching patient + start time."""
    date_str = appointment_start.strftime("%Y-%m-%d")

    try:
        appts = fhir.get_patient_appointments(patient_id, date_str)
    except Exception as exc:
        log.warning("cascade: FHIR patient appointment search failed: %s", exc)
        return []

    results: list[str] = []
    for appt in appts:
        status = appt.get("status", "")
        if status in ("cancelled", "noshow", "entered-in-error"):
            continue

        practitioner_id = _extract_practitioner_id(appt)
        if practitioner_id not in rr_staff_ids:
            continue

        appt_start_str = appt.get("start", "")
        if not appt_start_str:
            continue
        try:
            appt_start = datetime.datetime.fromisoformat(appt_start_str)
        except (ValueError, TypeError):
            continue

        # Normalise both to UTC for comparison.
        appt_utc = (
            appt_start.astimezone(datetime.timezone.utc)
            if appt_start.tzinfo
            else appt_start
        )
        ref_utc = (
            appointment_start.astimezone(datetime.timezone.utc)
            if appointment_start.tzinfo
            else appointment_start
        )

        if abs((appt_utc - ref_utc).total_seconds()) < 120:
            fhir_id = appt.get("id", "")
            if fhir_id:
                results.append(fhir_id)

    log.info(
        "cascade: found %d matching RR events for patient=%s, time=%s",
        len(results),
        patient_id,
        appointment_start.isoformat(),
    )
    return results


def _extract_practitioner_id(fhir_appt: dict[str, Any]) -> str:
    """Extract the Practitioner ID from a FHIR Appointment's participants."""
    for participant in fhir_appt.get("participant", []):
        actor_ref = participant.get("actor", {}).get("reference", "")
        if actor_ref.startswith("Practitioner/"):
            return str(actor_ref.split("/", 1)[1])
    return ""
