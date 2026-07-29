"""VisitConfirmed appointment-event connector.

Forwards Canvas appointment lifecycle events (created, rescheduled, cancelled,
no-show) to the VisitConfirmed platform, which then contacts the patient over
SMS and voice to confirm the visit and answer their questions. A patient who
asks for a new time is handed to practice staff; this connector is inbound only
and never writes appointments back into Canvas.

Scope of what this plugin sends: Canvas resource identifiers and scheduling
metadata only (appointment id, patient id, provider id, start time, duration).
It never sends patient names, phone numbers, email addresses, or clinical data,
and never logs them.

That is a claim about this plugin, not about the integration as a whole.
VisitConfirmed does read patient demographics, including name and contact
details, but over a separate channel: the practice's own Canvas FHIR API, via a
scoped credentialed connection under a Business Associate Agreement. Keep the
two channels distinct when describing this integration, because "no PHI leaves
Canvas" is false and "this plugin sends no PHI" is true.
"""

from typing import Any

import arrow
from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler
from canvas_sdk.utils import Http
from canvas_sdk.v1.data.appointment import Appointment
from logger import log

# Canvas event -> the event_type string Visit Confirmed expects in the payload.
EVENT_NAMES = {
    EventType.APPOINTMENT_CREATED: "appointment_created",
    EventType.APPOINTMENT_CANCELED: "appointment_canceled",
    EventType.APPOINTMENT_NO_SHOWED: "appointment_no_showed",
}


class AppointmentEvents(BaseHandler):
    """Notify Visit Confirmed when an appointment is created, cancelled, or no-showed.

    A create that points back at a prior appointment (Canvas models a reschedule
    as a new appointment linked via ``appointment_rescheduled_from``) is reported
    as ``appointment_rescheduled``.
    """

    RESPONDS_TO = [
        EventType.Name(EventType.APPOINTMENT_CREATED),
        EventType.Name(EventType.APPOINTMENT_CANCELED),
        EventType.Name(EventType.APPOINTMENT_NO_SHOWED),
    ]

    def compute(self) -> list[Effect]:
        """Build a minimal, PII-free event payload and POST it to Visit Confirmed."""
        api_url = self.secrets.get("VISIT_CONFIRMED_API_URL")
        api_key = self.secrets.get("VISIT_CONFIRMED_API_KEY")

        # `self.event.target.id`, not the `self.target` shortcut: that property is
        # deprecated in SDK 0.11.0 and removed in 1.0.0.
        appointment_id = self.event.target.id

        # Fail closed: with no endpoint or key configured, do nothing rather than
        # guess. A missing secret must never result in a half-formed outbound call.
        if not api_url or not api_key:
            log.error(
                "Visit Confirmed connector is not configured "
                "(VISIT_CONFIRMED_API_URL / VISIT_CONFIRMED_API_KEY missing); "
                "skipping appointment %s.",
                appointment_id,
            )
            return []

        event_name = EVENT_NAMES.get(self.event.type, "unknown")

        # Catch only the specific expected miss; anything else propagates to Sentry.
        try:
            appointment = Appointment.objects.get(id=appointment_id)
        except Appointment.DoesNotExist:
            log.error(
                "Visit Confirmed connector: appointment %s not found for event %s.",
                appointment_id,
                event_name,
            )
            return []

        appointment_payload: dict[str, Any] = {
            "id": str(appointment_id),
            "patient_id": str(appointment.patient.id) if appointment.patient else None,
            "provider_id": str(appointment.provider.id) if appointment.provider else None,
            "start_time": arrow.get(appointment.start_time).isoformat(),
            "duration_minutes": appointment.duration_minutes,
        }
        payload: dict[str, Any] = {
            "event_type": event_name,
            "timestamp": arrow.utcnow().isoformat(),
            "appointment": appointment_payload,
        }

        # Canvas represents a reschedule as a new appointment linked to the old one.
        if event_name == "appointment_created" and appointment.appointment_rescheduled_from:
            payload["event_type"] = "appointment_rescheduled"
            appointment_payload["rescheduled_from_id"] = str(
                appointment.appointment_rescheduled_from.id
            )

        # The payload carries no patient PII by design, so it is also safe NOT to
        # log it. Log identifiers and outcome only.
        http = Http()
        response = http.post(
            api_url,
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
        )

        if response.ok:
            log.info(
                "Visit Confirmed connector: sent %s for appointment %s.",
                payload["event_type"],
                appointment_id,
            )
        else:
            log.error(
                "Visit Confirmed connector: %s for appointment %s failed "
                "(status %s).",
                payload["event_type"],
                appointment_id,
                response.status_code,
            )

        # Pure forwarder: no Canvas-side effects to apply.
        return []
