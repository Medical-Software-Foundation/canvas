"""Originate the Reason-for-Visit command after an Appointment is created.

The /book endpoint stashes the user-typed RFV text in the plugin cache,
keyed by (patient_id, provider_id, start_time_utc). When Canvas creates
the Appointment and its associated Note, this handler reads the cached
text and originates a ``ReasonForVisitCommand`` on the note.
"""

from __future__ import annotations

from canvas_sdk.commands import ReasonForVisitCommand
from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.v1.data.appointment import Appointment
from logger import log

from scheduling_with_rooms.utils.rfv_cache import pop as pop_rfv


class ReasonForVisitOrigination(BaseProtocol):
    """On APPOINTMENT_CREATED, originate the RFV command on the appointment's note."""

    RESPONDS_TO = EventType.Name(EventType.APPOINTMENT_CREATED)

    def compute(self) -> list[Effect]:
        appointment_id = self.target
        log.info("rfv: APPOINTMENT_CREATED for %s", appointment_id)
        try:
            appointment = (
                Appointment.objects
                .select_related("note", "patient", "provider")
                .get(id=appointment_id)
            )
        except Appointment.DoesNotExist:
            log.warning("rfv: appointment %s not found", appointment_id)
            return []

        # The `*_id` attributes on ForeignKeys return integer dbids, not the
        # UUIDs the SimpleAPI receives. Read the UUIDs off the related models.
        patient_uuid = str(appointment.patient.id) if appointment.patient else ""
        provider_uuid = str(appointment.provider.id) if appointment.provider else ""

        log.info(
            "rfv: appt %s patient=%s provider=%s start_time=%r note=%s",
            appointment_id,
            patient_uuid,
            provider_uuid,
            appointment.start_time,
            appointment.note.id if appointment.note else None,
        )

        if not appointment.start_time or not patient_uuid or not provider_uuid:
            log.info("rfv: missing patient/provider/start_time on appointment %s; bailing", appointment_id)
            return []

        text = pop_rfv(
            patient_uuid,
            provider_uuid,
            appointment.start_time,
        )
        if not text:
            log.info("rfv: no cached text for appointment %s; nothing to originate", appointment_id)
            return []

        if not appointment.note:
            log.warning(
                "rfv: appointment %s has no note yet; skipping RFV origination "
                "(text_len=%d)", appointment_id, len(text),
            )
            return []

        note_uuid = str(appointment.note.id)
        log.info(
            "rfv: originating RFV command on note %s for appointment %s (text_len=%d)",
            note_uuid, appointment_id, len(text),
        )
        return [
            ReasonForVisitCommand(note_uuid=note_uuid, comment=text).originate(),
        ]
