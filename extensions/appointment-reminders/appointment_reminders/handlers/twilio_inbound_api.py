"""Twilio inbound-SMS webhook — structured Y/N appointment confirm/decline.

Public endpoint (Twilio cannot present a Canvas session); its security is the
``X-Twilio-Signature`` HMAC verified in ``authenticate()`` — fail closed. On a
verified reply:
  - "Y" → set the patient's nearest upcoming appointment to CONFIRMED
  - "N" → open an ops Task to follow up (distinguishes decline from no-response)
  - anything else → logged only (no action)
Every reply is recorded via ``log_inbound_response`` so it appears in the
activity log / "needs outreach" view. No PHI is sent or stored beyond the
patient's own reply text.
"""
from datetime import datetime, timezone
from http import HTTPStatus

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.effects import Effect
from canvas_sdk.effects.note.appointment import Appointment
from canvas_sdk.effects.simple_api import PlainTextResponse, Response
from canvas_sdk.effects.task import AddTask, TaskStatus
from canvas_sdk.handlers.simple_api import Credentials, SimpleAPI, api
from canvas_sdk.v1.data.appointment import AppointmentProgressStatus
from canvas_sdk.v1.data.appointment import Appointment as AppointmentModel
from canvas_sdk.v1.data.patient import Patient
from logger import log

from appointment_reminders.services.delivery import _normalize_phone
from appointment_reminders.services.history import log_inbound_response
from appointment_reminders.services.twilio_inbound import (
    classify_reply,
    parse_form_body,
    valid_twilio_signature,
)

_BOOKED_STATUSES = ["unconfirmed", "attempted", "confirmed"]

# Ignore a Twilio MessageSid we've already processed — a signed request that is
# replayed (e.g. from an intercepted log) must not double-act (duplicate decline
# Tasks / re-confirm). TTL is generous since legitimate SIDs are never reused.
_INBOUND_DEDUP_TTL = 7 * 24 * 60 * 60  # 7 days, in seconds


class TwilioInboundAPI(SimpleAPI):
    """Public, signature-gated webhook for inbound patient SMS replies."""

    def authenticate(self, credentials: Credentials) -> bool:
        """Endpoint is public — Twilio cannot present a Canvas session. Using the
        base ``Credentials`` type (not ``APIKeyCredentials``) avoids the
        framework's Authorization-header requirement; the real security is the
        ``X-Twilio-Signature`` HMAC verified in ``inbound()`` (fail closed)."""
        return True

    def _form_params(self) -> dict[str, str]:
        """Twilio's POST params as a flat str dict.

        Parses the raw body rather than using the SDK's ``form_data()``, because
        that accessor discards keys whose value is empty — it runs ``parse_qsl``
        without ``keep_blank_values``. Twilio includes empty-valued params
        (``FromCity``, ``FromZip``, ... when the carrier does not supply them) in
        the string it signs, so dropping them makes the recomputed HMAC differ
        and every genuine inbound SMS is rejected with 401.
        ``parse_form_body`` preserves blanks.

        Falls back to ``form_data()`` only when the raw body is unavailable.
        """
        params = parse_form_body(self.request.body)
        if params:
            return params
        try:
            data = self.request.form_data()
        except Exception:
            return {}
        return {k: getattr(v, "value", str(v)) for k, v in (data or {}).items()}

    def _signature_ok(self, params: dict[str, str]) -> bool:
        """Verify the X-Twilio-Signature over (webhook URL + sorted params)."""
        auth_token = self.secrets.get("twilio-auth-token")
        url = self.secrets.get("twilio-inbound-webhook-url")
        signature = self.request.headers.get("X-Twilio-Signature")
        return valid_twilio_signature(url, params, auth_token, signature)

    @api.post("/twilio/inbound")
    def inbound(self) -> list[Response | Effect]:
        """Handle an inbound SMS reply (signature-gated)."""
        params = self._form_params()

        # Security gate: reject anything without a valid Twilio signature.
        if not self._signature_ok(params):
            log.warning("[inbound] Rejected request with invalid Twilio signature")
            return [PlainTextResponse("unauthorized", status_code=HTTPStatus.UNAUTHORIZED)]

        # Replay guard: never act twice on the same Twilio MessageSid.
        message_sid = params.get("MessageSid", "")
        cache = get_cache()
        dedup_key = f"cr:inbound_seen:{message_sid}" if message_sid else ""
        if dedup_key and cache.get(dedup_key):
            log.info("[inbound] Duplicate MessageSid; ignoring replayed request")
            return [PlainTextResponse("", status_code=HTTPStatus.OK)]
        if dedup_key:
            cache.set(dedup_key, "1", timeout_seconds=_INBOUND_DEDUP_TTL)

        from_number = _normalize_phone(params.get("From", ""))
        body = params.get("Body", "")
        intent = classify_reply(body)

        patient = self._resolve_patient(from_number)
        if patient is None:
            log.info("[inbound] No patient matched inbound number; ignoring reply")
            return [PlainTextResponse("", status_code=HTTPStatus.OK)]

        appointment = self._nearest_upcoming_appointment(patient)
        effects: list[Response | Effect] = []
        status = intent

        if intent == "confirm":
            if appointment is not None:
                appt_effect = Appointment(instance_id=str(appointment.id))
                appt_effect.status = AppointmentProgressStatus.CONFIRMED
                effects.append(appt_effect.update())
                status = "confirmed"
                log.info(
                    f"[inbound] Confirmed appointment {appointment.id} "
                    f"for patient {patient.id}"
                )
            else:
                status = "confirmed_no_appointment"
        elif intent == "decline":
            effects.append(
                AddTask(
                    patient_id=str(patient.id),
                    title=(
                        "Patient declined an appointment reminder via SMS — "
                        "follow up to reschedule or cancel."
                    ),
                    status=TaskStatus.OPEN,
                    labels=["appointment-decline"],
                ).apply()
            )
            status = "declined"
            log.info(f"[inbound] Patient {patient.id} declined; opened follow-up task")

        log_inbound_response(
            patient_id=str(patient.id),
            appointment_id=str(appointment.id) if appointment else "",
            status=status,
            body=body,
            from_number=from_number,
        )
        effects.append(PlainTextResponse("", status_code=HTTPStatus.OK))
        return effects

    def _resolve_patient(self, from_number: str) -> Patient | None:
        """Find the patient who owns ``from_number`` (E.164), or None.

        Narrows candidates by the last 4 digits (format-agnostic) then confirms
        an exact normalized match — bounded work suitable for a webhook.
        """
        digits = "".join(c for c in (from_number or "") if c.isdigit())
        if len(digits) < 4:
            return None
        last4 = digits[-4:]
        candidates = (
            Patient.objects.filter(
                telecom__system="phone", telecom__value__contains=last4
            )
            .prefetch_related("telecom")
            .distinct()[:50]
        )
        for patient in candidates:
            for contact in patient.telecom.all():
                if (
                    contact.system == "phone"
                    and _normalize_phone(contact.value) == from_number
                ):
                    return patient
        return None

    def _nearest_upcoming_appointment(self, patient: Patient) -> AppointmentModel | None:
        """Return the patient's soonest upcoming booked appointment, or None."""
        now = datetime.now(timezone.utc)
        return (
            AppointmentModel.objects.filter(
                patient=patient,
                start_time__gte=now,
                status__in=_BOOKED_STATUSES,
            )
            .order_by("start_time")
            .first()
        )
