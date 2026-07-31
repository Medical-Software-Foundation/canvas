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

# Canvas event -> the event_type string VisitConfirmed expects in the payload.
EVENT_NAMES = {
    EventType.APPOINTMENT_CREATED: "appointment_created",
    EventType.APPOINTMENT_CANCELED: "appointment_canceled",
    EventType.APPOINTMENT_NO_SHOWED: "appointment_no_showed",
}


class AppointmentEvents(BaseHandler):
    """Notify VisitConfirmed when an appointment is created, cancelled, or no-showed.

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
        """Build a minimal, PII-free event payload and POST it to VisitConfirmed."""
        api_url = (self.secrets.get("VISIT_CONFIRMED_API_URL") or "").strip()
        api_key = (self.secrets.get("VISIT_CONFIRMED_API_KEY") or "").strip()

        # `self.event.target.id`, not the `self.target` shortcut: that property is
        # deprecated in SDK 0.11.0 and removed in 1.0.0.
        appointment_id = self.event.target.id

        # Fail closed: with no endpoint or key configured, do nothing rather than
        # guess. A missing secret must never result in a half-formed outbound call.
        if not api_url or not api_key:
            log.error(
                "VisitConfirmed connector is not configured "
                "(VISIT_CONFIRMED_API_URL / VISIT_CONFIRMED_API_KEY missing); "
                "skipping appointment %s.",
                appointment_id,
            )
            return []

        # The API key travels in an Authorization header, so refuse any scheme that
        # would put it on the wire in cleartext. canvas_sdk's Http does NOT check
        # this: constructed with no base_url, its join_url containment check
        # (`joined.startswith("")`) is always true, so an http:// value configured
        # here would send the key unencrypted. Fail closed on anything but https.
        #
        # A prefix test rather than urllib.parse.urlparse, which the plugin sandbox
        # refuses to import ("'urlparse' is not an allowed import from
        # 'urllib.parse'"). Schemes are case-insensitive, hence the lower().
        if not api_url.lower().startswith("https://"):
            log.error(
                "VisitConfirmed connector: VISIT_CONFIRMED_API_URL must use https; "
                "refusing to send credentials for appointment %s.",
                appointment_id,
            )
            return []

        event_name = EVENT_NAMES.get(self.event.type, "unknown")

        # entered_in_error__isnull=True excludes retracted appointments, which must
        # never trigger patient outreach. select_related avoids a separate query per
        # related object when the payload reads patient.id and provider.id below.
        # Catch only the specific expected miss; anything else propagates to Sentry.
        try:
            appointment = Appointment.objects.select_related("patient", "provider").get(
                id=appointment_id,
                entered_in_error__isnull=True,
            )
        except Appointment.DoesNotExist:
            log.error(
                "VisitConfirmed connector: appointment %s not found, or entered in "
                "error, for event %s.",
                appointment_id,
                event_name,
            )
            return []

        # start_time is declared non-null on the SDK model, so this is a guard rather
        # than an observed failure. It is here because arrow.get(None) raises
        # TypeError, which would take down the handler for a malformed record.
        if not appointment.start_time:
            log.error(
                "VisitConfirmed connector: appointment %s has no start time; "
                "skipping event %s.",
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
                "VisitConfirmed connector: sent %s for appointment %s.",
                payload["event_type"],
                appointment_id,
            )
        else:
            log.error(
                "VisitConfirmed connector: %s for appointment %s failed "
                "(status %s).",
                payload["event_type"],
                appointment_id,
                response.status_code,
            )

        # Pure forwarder: no Canvas-side effects to apply.
        return []
