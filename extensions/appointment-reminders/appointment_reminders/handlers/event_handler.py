"""Event handler for appointment notification events."""
from canvas_sdk.effects import Effect
from canvas_sdk.effects.appointments_metadata import AppointmentsMetadata
from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler
from canvas_sdk.v1.data.appointment import Appointment
from canvas_sdk.v1.data.patient import Patient
from logger import log

from appointment_reminders.services.business_line import (
    get_business_line_from_number,
    get_business_line_name,
)
from appointment_reminders.services.config import get_effective_campaign_config, load_config
from appointment_reminders.services.delivery import deliver_to_patient
from appointment_reminders.services.history import log_delivery
from appointment_reminders.services.templates import get_template_variables, render_template


# Map event types to campaign types
_EVENT_TO_CAMPAIGN = {
    EventType.Name(EventType.APPOINTMENT_CREATED): "confirmation",
    EventType.Name(EventType.APPOINTMENT_CANCELED): "cancellation",
    EventType.Name(EventType.APPOINTMENT_NO_SHOWED): "noshow",
}


class AppointmentEventHandler(BaseHandler):
    """Handle appointment events for instant patient notifications."""

    RESPONDS_TO = [
        EventType.Name(EventType.APPOINTMENT_CREATED),
        EventType.Name(EventType.APPOINTMENT_UPDATED),
        EventType.Name(EventType.APPOINTMENT_CANCELED),
        EventType.Name(EventType.APPOINTMENT_NO_SHOWED),
    ]

    def compute(self) -> list[Effect]:
        """Send appropriate notification based on event type."""
        event_type = self.event.name
        appointment_id = self.event.target.id

        patient_id = self.event.context.get("patient", {}).get("id")

        if not patient_id:
            log.warning(
                f"[notify] No patient ID in context for appointment {appointment_id}"
            )
            return []

        config = load_config()

        effects: list[Effect] = []

        is_create_or_update = event_type in (
            EventType.Name(EventType.APPOINTMENT_CREATED),
            EventType.Name(EventType.APPOINTMENT_UPDATED),
        )
        campaign_type = _EVENT_TO_CAMPAIGN.get(event_type)

        # Skip the appointment fetch entirely when neither branch needs it
        if not is_create_or_update and not campaign_type:
            return effects

        try:
            appointment = (
                Appointment.objects.select_related(
                    "note_type", "patient", "provider", "location"
                )
                .prefetch_related(
                    "provider__roles", "location__addresses", "location__telecom"
                )
                .get(id=appointment_id)
            )
        except Appointment.DoesNotExist:
            log.warning(f"[notify] Appointment {appointment_id} not found")
            return effects

        if not campaign_type:
            return effects

        try:
            patient = (
                Patient.objects.select_related("business_line")
                # `addresses` is read by the timezone resolver, which renders the
                # appointment time in the patient's own zone rather than the
                # clinic's.
                .prefetch_related("telecom", "addresses")
                .get(id=patient_id)
            )
        except Patient.DoesNotExist:
            log.error(f"[notify] Patient {patient_id} not found")
            return effects

        note_type_id = str(appointment.note_type.id) if appointment.note_type else None
        business_line = get_business_line_name(patient)

        enabled, channels, sms_template, email_template, *_ = (
            get_effective_campaign_config(
                config, note_type_id, campaign_type, business_line=business_line
            )
        )

        if not enabled:
            meta = AppointmentsMetadata(
                appointment_id=str(appointment_id), key=f"notify:{campaign_type}"
            )
            effects.append(meta.upsert(value=f"skipped|campaign_disabled|note_type={note_type_id}"))
            return effects

        variables = get_template_variables(
            patient, appointment, config.reminder_timezone, config=config
        )
        sms_content = render_template(sms_template, variables)
        email_content = render_template(email_template, variables)

        log.info(f"[notify] Sending {campaign_type} for appointment {appointment_id}")
        delivery_effects, results = deliver_to_patient(
            patient,
            sms_content,
            email_content,
            channels,
            campaign_type,
            self.secrets,
            str(appointment_id),
            from_number=get_business_line_from_number(config, business_line),
            config=config,
        )
        effects.extend(delivery_effects)

        log_delivery(
            str(appointment_id), str(patient_id), campaign_type, results,
            sms_content=sms_content, email_content=email_content,
        )

        return effects
