"""Event handler for appointment notification events."""
from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler
from canvas_sdk.v1.data.appointment import Appointment
from canvas_sdk.v1.data.patient import Patient
from logger import log

from patient_notify.services.config import get_effective_campaign_config, load_config, resolve_templates
from patient_notify.services.delivery import deliver_to_patient
from patient_notify.services.history import log_delivery_to_cache
from patient_notify.services.templates import get_template_variables, render_template

_EVENT_TO_CAMPAIGN = {
    EventType.Name(EventType.APPOINTMENT_CREATED): "confirmation",
    EventType.Name(EventType.APPOINTMENT_CANCELED): "cancellation",
    EventType.Name(EventType.APPOINTMENT_NO_SHOWED): "noshow",
}


class AppointmentEventHandler(BaseHandler):
    """Handle appointment events for instant patient notifications."""

    RESPONDS_TO = [
        EventType.Name(EventType.APPOINTMENT_CREATED),
        EventType.Name(EventType.APPOINTMENT_CANCELED),
        EventType.Name(EventType.APPOINTMENT_NO_SHOWED),
    ]

    def compute(self) -> list[Effect]:
        """Send appropriate notification based on event type."""
        event_type = self.event.name
        appointment_id = self.event.target.id
        patient_id = self.event.context.get("patient", {}).get("id")

        if not patient_id:
            log.warning(f"No patient ID in context for appointment {appointment_id}")
            return []

        config = load_config()

        campaign_type = _EVENT_TO_CAMPAIGN.get(event_type)
        if not campaign_type:
            log.info(f"No campaign mapping for event type {event_type}")
            return []

        try:
            patient = Patient.objects.prefetch_related("telecom").get(id=patient_id)
        except Patient.DoesNotExist:
            log.error(f"[AppointmentEventHandler] Patient {patient_id} not found")
            return []

        try:
            appointment = Appointment.objects.select_related(
                "provider", "location", "note_type"
            ).get(id=appointment_id)
        except Appointment.DoesNotExist:
            log.error(f"[AppointmentEventHandler] Appointment {appointment_id} not found")
            return []

        note_type = appointment.note_type
        note_type_id = str(note_type.id) if note_type else None

        enabled, _intervals, channels, _sms, _email, _send_time = (
            get_effective_campaign_config(config, campaign_type, note_type_id)
        )

        if not enabled:
            log.info(f"Campaign {campaign_type} disabled for note type {note_type_id}")
            return []

        sms_template, email_template = resolve_templates(config, campaign_type, note_type_id)
        variables = get_template_variables(patient, appointment, config=config, note_type=note_type)
        sms_content = render_template(sms_template, variables)
        email_content = render_template(email_template, variables)

        log.info(f"Sending {campaign_type} notification for appointment {appointment_id}")
        effects, results = deliver_to_patient(
            patient,
            sms_content,
            email_content,
            channels,
            campaign_type,
            self.secrets,
        )

        log_delivery_to_cache(
            str(appointment_id), str(patient_id), campaign_type, results
        )

        return effects
