"""Twilio inbound-SMS webhook — structured Y/N appointment confirm/decline.

Public endpoint (Twilio cannot present a Canvas session); its security is the
``X-Twilio-Signature`` HMAC verified in ``authenticate()`` — fail closed. On a
verified reply:
  - "Y" → set the patient's nearest upcoming appointment to CONFIRMED
  - "N" → open an ops Task to follow up (distinguishes decline from no-response)
  - a Twilio opt-out keyword → clear SMS consent on the number that texted in
  - a Twilio opt-in keyword → restore it
  - anything else → logged only (no action)
Consent is classified separately from appointment intent because Twilio's
keyword set overlaps ours: YES is both an opt-in and a confirm, and both halves
are actioned. CANCEL is an opt-out only — Twilio publishes it as an unsubscribe
synonym, so it is not read as an appointment decline.
Every reply is recorded: ``log_inbound_response`` when the sender resolves to a
patient, ``log_unresolved_sender`` when it does not, so a reply from a number on
no chart is distinguishable from no reply at all. Nothing is stored beyond the
sender's number and their own reply text — which for an unresolved sender means
a number belonging to nobody on file, retained so staff can follow it up.
"""
import zoneinfo
from datetime import datetime, timezone
from datetime import time as dt_time
from http import HTTPStatus
from typing import Any

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.effects import Effect
from canvas_sdk.effects.note.appointment import Appointment
from canvas_sdk.effects.simple_api import PlainTextResponse, Response
from canvas_sdk.effects.task import AddTask, TaskStatus
from canvas_sdk.handlers.simple_api import Credentials, SimpleAPI, api
from canvas_sdk.v1.data.appointment import AppointmentProgressStatus
from canvas_sdk.v1.data.appointment import Appointment as AppointmentModel
from canvas_sdk.v1.data.patient import Patient
from canvas_sdk.v1.data.team import Team
from logger import log

from appointment_reminders.services.config import load_config
from appointment_reminders.services.consent import sms_consent_effect
from appointment_reminders.services.delivery import _normalize_phone
from appointment_reminders.services.history import (
    log_inbound_response,
    log_unresolved_sender,
)
from appointment_reminders.services.twilio_inbound import (
    classify_consent,
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
        consent = classify_consent(body)

        patient = self._resolve_patient(from_number)
        if patient is None:
            # Audited, not just logged. The appointment stays unconfirmed either
            # way, and without a row that is indistinguishable from the patient
            # never replying — when in fact they did, from a number on no chart.
            log.warning(
                "[inbound] Verified reply from a number on no chart; "
                "recorded as unresolved_sender"
            )
            log_unresolved_sender(body=body, from_number=from_number)
            return [PlainTextResponse("", status_code=HTTPStatus.OK)]

        appointment = self._nearest_upcoming_appointment(patient)
        effects: list[Response | Effect] = []
        status = intent

        # Consent first: Twilio has already blocked or unblocked the number on
        # its side, and mirroring that onto the chart is what keeps the plugin
        # from texting someone Twilio will refuse to deliver to (error 21610).
        if consent:
            consent_effect = sms_consent_effect(
                patient, from_number, has_consent=(consent == "opt_in")
            )
            if consent_effect is not None:
                effects.append(consent_effect)
                log.info(
                    f"[inbound] Patient {patient.id} texted a Twilio {consent} keyword; "
                    f"SMS consent {'restored' if consent == 'opt_in' else 'cleared'}"
                )
            else:
                log.info(
                    f"[inbound] Patient {patient.id} texted a Twilio {consent} keyword; "
                    "chart already agrees, no write"
                )

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
            # One read for both task settings; still only on this branch, so
            # every other reply path stays free of a config query.
            task_config = load_config()
            effects.append(
                AddTask(
                    patient_id=str(patient.id),
                    team_id=self._decline_task_team_id(task_config),
                    due=self._decline_task_due(task_config),
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

        # One audit row per reply, so a keyword that carries both a consent
        # change and an appointment intent (CANCEL, YES) records both rather
        # than losing one to the other.
        parts = []
        if consent:
            parts.append("opted_in" if consent == "opt_in" else "opted_out")
        if status != "unrecognized":
            parts.append(status)
        status = "+".join(parts) or "unrecognized"

        log_inbound_response(
            patient_id=str(patient.id),
            appointment_id=str(appointment.id) if appointment else "",
            status=status,
            body=body,
            from_number=from_number,
        )
        effects.append(PlainTextResponse("", status_code=HTTPStatus.OK))
        return effects

    def _decline_task_due(self, config: Any) -> datetime | None:
        """End of today in the instance's timezone, or None when switched off.

        A task with no due date sorts nowhere and gets lost in a large queue,
        which is what prompted this. End of day rather than "now" so the task
        reads as due today without arriving already overdue.

        The date is anchored to the instance's own timezone
        (``INSTALLATION_TIME_ZONE``), because ``due`` is a timestamp and not a
        date: end of day computed in UTC would render as the *previous* day for
        any instance behind it — 23:59 UTC is 19:59 the same evening in Eastern,
        but midnight UTC is the evening before. Falls back to UTC with a warning
        if the environment does not supply a zone, which keeps the date right for
        US instances and merely shifts the hour.
        """
        if not getattr(config, "decline_task_due_end_of_day", False):
            return None
        tz_name = (self.environment or {}).get("INSTALLATION_TIME_ZONE") or ""
        try:
            tz = zoneinfo.ZoneInfo(tz_name) if tz_name else timezone.utc
        except zoneinfo.ZoneInfoNotFoundError:
            log.warning(
                f"[inbound] Unknown INSTALLATION_TIME_ZONE {tz_name!r}; "
                "using UTC for the decline task due date"
            )
            tz = timezone.utc
        if not tz_name:
            log.warning(
                "[inbound] No INSTALLATION_TIME_ZONE in the environment; "
                "using UTC for the decline task due date"
            )
        local_today = datetime.now(tz).date()
        return datetime.combine(local_today, dt_time(23, 59, 59), tzinfo=tz)

    def _decline_task_team_id(self, config: Any) -> str | None:
        """The configured team for decline follow-ups, or None for unassigned.

        Verifies the team still exists. A configured team can be deleted in
        Canvas long after it was chosen here, and handing ``AddTask`` a dangling
        id risks losing the whole effect — which would mean losing the task, the
        one artifact telling staff this patient wants to reschedule. An
        unassigned task in someone's way beats no task at all.

        Takes the config rather than loading it, so the decline branch pays for
        one read shared with the due-date lookup.
        """
        team_id = (getattr(config, "decline_task_team_id", "") or "").strip()
        if not team_id:
            return None
        if not Team.objects.filter(id=team_id).exists():
            log.warning(
                f"[inbound] Configured decline-task team {team_id} no longer "
                "exists; creating the task unassigned"
            )
            return None
        return team_id

    def _resolve_patient(self, from_number: str) -> Patient | None:
        """Find the patient who owns ``from_number`` (E.164), or None.

        Filters on the last 10 digits as a *suffix*. Both sides of the
        comparison are already canonical: the caller normalizes Twilio's
        ``From`` to E.164 via ``_normalize_phone``, and stored contact-point
        values are bare digits. So the suffix is precise enough to return the
        one matching patient rather than a crowd of near-misses.

        An earlier version narrowed on the last **4** digits with ``__contains``
        and capped the result at 50 rows of an unordered queryset — ``LIMIT 50``
        with no ``ORDER BY``, so the rows kept were arbitrary. At production
        scale that lookup returned roughly 200 candidates and discarded three
        quarters of them before the exact-match loop, so most real replies never
        resolved. Not flaky, either: the slice is arbitrary but stable, so a
        given patient tended to fail consistently. The 4-digit prefilter was
        defending against punctuation variation that occurs on neither side.

        The Python pass stays: it confirms the exact normalized match, so a
        suffix collision between two different numbers cannot resolve wrongly.
        """
        digits = "".join(c for c in (from_number or "") if c.isdigit())
        if len(digits) < 10:
            return None
        suffix = digits[-10:]
        # Deliberately uncapped. After a 10-digit suffix match, more than one
        # hit means genuinely duplicated patient records — a data-quality
        # problem the caller should see rather than have silently truncated.
        candidates = (
            Patient.objects.filter(
                telecom__system="phone", telecom__value__endswith=suffix
            )
            .prefetch_related("telecom")
            .distinct()
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
