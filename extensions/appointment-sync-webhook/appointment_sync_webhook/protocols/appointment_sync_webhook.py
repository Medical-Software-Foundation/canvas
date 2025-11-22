"""
Appointment Sync Webhook Handler

This webhook handler listens for appointment lifecycle events in Canvas and
sends notifications to an external webhook endpoint. This enables external
systems (like custom member portals) to stay in sync with appointment changes
made directly in the Canvas UI.

Events handled:
- APPOINTMENT_CREATED: When an appointment is first created/booked, 
    this also includes rescheduled appointments by providers in the Canvas UI
- APPOINTMENT_CANCELED: When an appointment is cancelled
- APPOINTMENT_NO_SHOWED: When a patient is marked as a no-show
"""
import arrow
from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler
from canvas_sdk.utils import Http
from canvas_sdk.v1.data.appointment import Appointment
from logger import log


class AppointmentSyncWebhook(BaseHandler):
    """
    Webhook handler that notifies an external system whenever appointments are
    created, cancelled, or marked as no-show in Canvas.

    This allows external systems to maintain synchronized appointment status
    without polling or manual updates.
    """

    # Respond to appointment lifecycle events
    RESPONDS_TO = [
        EventType.Name(EventType.APPOINTMENT_CREATED),
        EventType.Name(EventType.APPOINTMENT_CANCELED),
        EventType.Name(EventType.APPOINTMENT_NO_SHOWED),
    ]

    def compute(self):
        """
        Triggered when an appointment is created, cancelled, or marked as no-show.

        Sends a webhook notification with appointment and patient details to the
        configured endpoint.
        """
        # Get the webhook URL from plugin secrets configuration
        # Set this in the Canvas admin panel: /admin/plugin_io/plugin/
        webhook_url = self.secrets.get('WEBHOOK_URL')

        if not webhook_url:
            log.error("WEBHOOK_URL not configured in plugin secrets. Skipping webhook notification.")
            return []

        # The target of the event is the appointment ID
        appointment_id = self.target

        # Determine the event type
        event_type_map = {
            EventType.APPOINTMENT_CREATED: 'appointment_created',
            EventType.APPOINTMENT_CANCELED: 'appointment_canceled',
            EventType.APPOINTMENT_NO_SHOWED: 'appointment_no_showed',
        }

        event_name = event_type_map.get(self.event.type, 'unknown')
        now = arrow.utcnow().isoformat()

        # Fetch the full appointment object to get additional details
        try:
            appointment = Appointment.objects.get(id=appointment_id)

             # Build the webhook payload with appointment details
            payload = {
                "event_type": event_name,
                "appointment": {
                    "id": appointment_id,
                    "provider_id": str(appointment.provider.id),
                    "start_time": arrow.get(appointment.start_time).isoformat(),
                    "duration_minutes": appointment.duration_minutes,
                    "end_time": arrow.get(appointment.start_time).shift(minutes=appointment.duration_minutes).isoformat(),
                    # Add more attributes as needed
                },
                "timestamp": now,
            }

            # If the appointment is rescheduled, get the original appointment
            if event_name == 'appointment_created' and appointment.appointment_rescheduled_from:
                original_appointment = Appointment.objects.get(id=appointment.appointment_rescheduled_from.id)
                payload['event_type'] = 'appointment_rescheduled'
                payload["appointment"]["original_appointment"] = {
                    "id": str(original_appointment.id),
                    "provider_id": str(original_appointment.provider.id),
                    "start_time": arrow.get(original_appointment.start_time).isoformat(),
                    "duration_minutes": original_appointment.duration_minutes,
                    "end_time": arrow.get(original_appointment.start_time).shift(minutes=original_appointment.duration_minutes).isoformat(),
                }

            # Optionally include patient details
            if appointment.patient:
                try:
                    payload["patient"] = {
                        "id": str(appointment.patient.id),
                        "first_name": appointment.patient.first_name,
                        "last_name": appointment.patient.last_name,
                    }
                except Exception as e:
                    log.warning(f"Could not fetch patient details for patient_id={appointment.patient.id}: {e}")

        except Exception as e:
            log.error(f"Error fetching appointment details for appointment_id={appointment_id}: {e}")
            # Send minimal payload if we can't fetch full appointment details
            # Get patient_id from event context if available
            patient_id = self.event.context.get('patient', {}).get('id')
            payload = {
                "event_type": event_name,
                "appointment": {
                    "id": appointment_id,
                    "patient_id": patient_id,
                },
                "timestamp": now,
                "error": "Could not fetch full appointment details"
            }

        # Send the webhook notification to the external system
        try:
            log.info(f"Sending webhook notification to {webhook_url} with payload: {payload}")
            http = Http()
            response = http.post(webhook_url, json=payload)

            if response.ok:
                log.info(f"Successfully sent {event_name} webhook for appointment_id={appointment_id}")
            else:
                log.error(
                    f"Webhook notification failed for {event_name}. "
                    f"Status: {response.status_code}, Response: {response.text}"
                )
        except Exception as e:
            log.error(f"Exception sending webhook for {event_name}: {e}")

        # BaseHandler subclasses must return a list (can be empty) to indicate success
        return []
