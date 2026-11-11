"""Twilio inbound-SMS webhook — structured Y/N appointment confirm/decline.

Public endpoint (Twilio cannot present a Canvas session); its security is the
``X-Twilio-Signature`` HMAC verified in ``authenticate()`` — fail closed. On a
verified reply:
  - "Y" → set the patient's nearest upcoming appointment to CONFIRMED, but only
    if an appointment SMS for it went out within ``confirm_reply_window_days``;
    otherwise the "Y" is treated as an unrecognized reply
  - "N" → open an ops Task to follow up (distinguishes decline from no-response)
  - a Twilio opt-out keyword → clear SMS consent on the number that texted in
  - a Twilio opt-in keyword → restore it
  - anything else → logged, plus a follow-up Task when
    ``other_reply_task_enabled`` is on
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
from datetime import UTC, date, datetime, timedelta, timezone
from datetime import time as dt_time
from http import HTTPStatus
from typing import Any

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

from appointment_reminders.models.delivery import NotificationDelivery
from appointment_reminders.services.claims import INBOUND, claim_store
from appointment_reminders.services.config import load_config, parse_hhmm
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

# Outbound campaigns about an upcoming appointment, so the ones a confirm reply
# can be answering. See _appointment_sms_sent_recently.
_REPLYABLE_CAMPAIGNS = ["reminder", "telehealth", "confirmation"]

# Most recent sent-SMS rows read when several charts share the sending number.
_SHARED_NUMBER_ROW_LIMIT = 50

# Longest stretch of the patient's reply quoted in a follow-up task title.
_TASK_QUOTE_LIMIT = 120

# Saturday and Sunday, per date.weekday()
_WEEKEND = (5, 6)


def _add_business_days(start: date, days: int) -> date:
    """Advance ``days`` business days from ``start``, skipping weekends.

    A weekend ``start`` rolls forward first, so an offset of 0 on a Saturday is
    due Monday rather than the same day nobody is working. Then each step lands
    on a weekday: Friday + 1 is Monday, Friday + 2 is Tuesday.

    Weekends only. Canvas exposes no holiday calendar a plugin can read, so a
    task due on a public holiday is left as-is rather than guessed at.
    """
    current = start
    while current.weekday() in _WEEKEND:
        current += timedelta(days=1)
    remaining = days
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() not in _WEEKEND:
            remaining -= 1
    return current

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
        #
        # Persisted as a row rather than a cache entry. The plugins cache culls
        # once it passes 300 entries, and this marker had the longest TTL in the
        # plugin (7 days), so it was both the likeliest to be evicted and the
        # most costly to lose: acting twice re-applies the appointment status,
        # re-writes consent, and opens a second follow-up task. Claiming is a
        # single atomic insert, so a genuine Twilio retry and a replayed capture
        # are both refused by the same check.
        # ``claim`` also consults the legacy cache key for one release, so a
        # retry of a message the pre-table version handled is still refused.
        message_sid = params.get("MessageSid", "")
        claims = claim_store()
        if message_sid and not claims.claim(INBOUND, message_sid):
            log.info("[inbound] Duplicate MessageSid; ignoring replayed request")
            return [PlainTextResponse("", status_code=HTTPStatus.OK)]

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

        # Read at most once per reply, and only on the paths that need it, so a
        # STOP or START stays free of a config query.
        config = None

        if intent == "confirm":
            config = load_config()
            # A confirm only counts as an answer to an appointment SMS we sent.
            # The number also carries other traffic (portal invites, staff
            # messages), and a YES to one of those must not confirm whichever
            # appointment happens to be next. No recent appointment SMS means
            # the reply is handled exactly like any other unrecognized text.
            if appointment is not None and self._appointment_sms_sent_recently(
                patient, appointment, config.confirm_reply_window_days
            ):
                appt_effect = Appointment(instance_id=str(appointment.id))
                appt_effect.status = AppointmentProgressStatus.CONFIRMED
                effects.append(appt_effect.update())
                status = "confirmed"
                log.info(
                    f"[inbound] Confirmed appointment {appointment.id} "
                    f"for patient {patient.id}"
                )
            else:
                status = "unrecognized"
                log.info(
                    f"[inbound] Patient {patient.id} sent a confirm reply with no "
                    "appointment SMS in the confirm window; not confirming"
                )
        elif intent == "decline":
            # One read for both task settings.
            config = load_config()
            effects.append(
                AddTask(
                    patient_id=str(patient.id),
                    team_id=self._decline_task_team_id(config),
                    due=self._decline_task_due(config),
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

        # A reply nobody acted on. A bare consent keyword (STOP, START, ...) is
        # not one: Twilio has handled it and the consent write above mirrors
        # it. A YES that could not confirm is one, even though it also opted
        # the patient back in, because the patient was answering something.
        needs_review = status == "unrecognized" and (
            not consent or intent == "confirm"
        )
        if needs_review:
            if config is None:
                config = load_config()
            if config.other_reply_task_enabled:
                effects.append(self._other_reply_task(patient, body, config))
                log.info(
                    f"[inbound] Patient {patient.id} sent an unrecognized reply; "
                    "opened follow-up task"
                )

        # One audit row per reply, so a keyword that carries both a consent
        # change and an appointment intent (CANCEL, YES) records both rather
        # than losing one to the other. A YES that could not confirm records
        # "opted_in+unrecognized", so the unconfirmed reply stays visible.
        parts = []
        if consent:
            parts.append("opted_in" if consent == "opt_in" else "opted_out")
        if status != "unrecognized" or needs_review:
            parts.append(status)
        status = "+".join(parts) or "unrecognized"

        log_inbound_response(
            patient_id=str(patient.id),
            appointment_id=str(appointment.id) if appointment else "",
            status=status,
            body=body,
            from_number=from_number,
            # Resolved from the sender's number earlier in this request.
            patient=patient,
        )
        effects.append(PlainTextResponse("", status_code=HTTPStatus.OK))
        return effects

    def _decline_task_due(self, config: Any) -> datetime | None:
        """When the decline follow-up task is due, or None when unset.

        ``decline_task_due_days`` is a number of **business days** from the day
        the patient replied — 0 meaning that same day — and
        ``decline_task_due_time`` the local time of day. A task with no due date
        sorts nowhere and gets lost in a large queue, which is what prompted it.

        Anchored to the instance's timezone (``INSTALLATION_TIME_ZONE``) because
        ``due`` is a timestamp, not a date: computing it in UTC would render as
        the *previous* day for any instance behind UTC — midnight UTC is the
        evening before in Eastern. Falls back to UTC with a warning if the
        environment has no zone, which keeps the date right for US instances and
        merely shifts the hour, rather than silently dropping a configured rule.

        Defaults to 23:59 rather than the reply moment so the task reads as due
        without arriving already overdue.
        """
        days = getattr(config, "decline_task_due_days", None)
        if days is None:
            return None

        tz = self._instance_timezone()
        hour, minute = parse_hhmm(
            getattr(config, "decline_task_due_time", "") or "", (23, 59)
        )
        due_date = _add_business_days(datetime.now(tz).date(), int(days))
        return datetime.combine(due_date, dt_time(hour, minute), tzinfo=tz)

    def _instance_timezone(self) -> Any:
        """The instance's configured timezone, or UTC with a warning."""
        tz_name = (self.environment or {}).get("INSTALLATION_TIME_ZONE") or ""
        if not tz_name:
            log.warning(
                "[inbound] No INSTALLATION_TIME_ZONE in the environment; "
                "using UTC for the decline task due date"
            )
            return timezone.utc
        try:
            return zoneinfo.ZoneInfo(tz_name)
        except zoneinfo.ZoneInfoNotFoundError:
            log.warning(
                f"[inbound] Unknown INSTALLATION_TIME_ZONE {tz_name!r}; "
                "using UTC for the decline task due date"
            )
            return timezone.utc

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
        return self._existing_team_id(
            getattr(config, "decline_task_team_id", ""), "decline-task"
        )

    def _existing_team_id(self, team_id: str | None, purpose: str) -> str | None:
        """``team_id`` if it names a team that still exists, else None."""
        team_id = (team_id or "").strip()
        if not team_id:
            return None
        if not Team.objects.filter(id=team_id).exists():
            log.warning(
                f"[inbound] Configured {purpose} team {team_id} no longer "
                "exists; creating the task unassigned"
            )
            return None
        return team_id

    def _other_reply_task(self, patient: Patient, body: str, config: Any) -> Effect:
        """Follow-up task for a reply the plugin could not act on.

        Same shape as the decline task (team check, business-day due date), with
        its own team. The reply is quoted in the title because that is what
        staff need to triage it, and the task lives on the patient's chart, the
        same place the reply already shows in the patient panel's history.
        """
        quoted = " ".join((body or "").split())
        if len(quoted) > _TASK_QUOTE_LIMIT:
            quoted = quoted[: _TASK_QUOTE_LIMIT - 1] + "…"
        return AddTask(
            patient_id=str(patient.id),
            team_id=self._existing_team_id(
                getattr(config, "other_reply_task_team_id", ""), "other-reply-task"
            ),
            due=self._decline_task_due(config),
            title=f'Patient replied by SMS — review and follow up: "{quoted}"',
            status=TaskStatus.OPEN,
            labels=["sms-reply"],
        ).apply()

    def _appointment_sms_sent_recently(
        self, patient: Patient, appointment: AppointmentModel, window_days: int
    ) -> bool:
        """Whether an appointment SMS for ``appointment`` went out recently.

        True when Twilio accepted a reminder, telehealth-join or booking SMS
        for this appointment within ``window_days``. Those are the messages that
        can ask a patient to reply; a no-show or cancellation message is about
        an appointment that is no longer upcoming, so it cannot be what a
        confirm for the next one answers.

        One indexed ``EXISTS``: the patient filter rides the
        ``(patient, -created_at)`` index, which narrows to this patient's few
        rows before the rest of the predicate is checked. ``patient_id`` is the
        FK column, which holds the patient's ``dbid``, so no join is needed.
        """
        cutoff = datetime.now(UTC) - timedelta(days=window_days)
        return NotificationDelivery.objects.filter(
            patient_id=patient.dbid,
            appointment_id=str(appointment.id),
            campaign_type__in=_REPLYABLE_CAMPAIGNS,
            channel="sms",
            status="accepted",
            created_at__gte=cutoff,
        ).exists()

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
        When more than one chart matches exactly, ``_pick_shared_number_patient``
        decides which one the reply belongs to.
        """
        digits = "".join(c for c in (from_number or "") if c.isdigit())
        if len(digits) < 10:
            return None
        suffix = digits[-10:]
        # Deliberately uncapped. After a 10-digit suffix match, more than one
        # hit means charts that genuinely share the number (family members, or
        # duplicated records), and every one of them must be weighed.
        candidates = (
            Patient.objects.filter(
                telecom__system="phone", telecom__value__endswith=suffix
            )
            .prefetch_related("telecom")
            .distinct()
        )
        matches = [
            patient
            for patient in candidates
            if any(
                contact.system == "phone"
                and _normalize_phone(contact.value) == from_number
                for contact in patient.telecom.all()
            )
        ]
        if len(matches) <= 1:
            return matches[0] if matches else None
        return self._pick_shared_number_patient(matches, from_number)

    def _pick_shared_number_patient(
        self, matches: list[Patient], from_number: str
    ) -> Patient:
        """Choose among several charts that carry the same phone number.

        Family members often share one number, and the reply belongs to the
        chart we texted, not whichever chart the lookup happened to return
        first. Using this plugin's own sent-SMS rows to that number:

        1. If exactly one chart has an upcoming booked appointment that a
           reminder, telehealth or booking SMS was about within the confirm
           window, that chart — it is the one with something to reply to.
        2. Otherwise the chart we most recently texted at this number.
        3. With no sent rows at all, the first match, as before.

        Only reached when more than one chart matches, so the single-chart path
        pays no extra query.
        """
        by_dbid = {patient.dbid: patient for patient in matches}
        # Newest first, capped: only the latest sends to this number matter.
        sent = list(
            NotificationDelivery.objects.filter(
                patient_id__in=list(by_dbid),
                recipient=from_number,
                channel="sms",
                status="accepted",
            )
            .order_by("-created_at")
            .values_list("patient_id", "appointment_id", "campaign_type", "created_at")[
                :_SHARED_NUMBER_ROW_LIMIT
            ]
        )
        if not sent:
            log.warning(
                f"[inbound] {len(matches)} charts share the sending number and "
                f"none was texted by this plugin; using patient {matches[0].id}"
            )
            return matches[0]

        window_days = load_config().confirm_reply_window_days
        cutoff = datetime.now(UTC) - timedelta(days=window_days)
        reminded = {
            str(appointment_id): patient_dbid
            for patient_dbid, appointment_id, campaign, created_at in sent
            if appointment_id
            and campaign in _REPLYABLE_CAMPAIGNS
            and created_at >= cutoff
        }
        if reminded:
            upcoming = AppointmentModel.objects.filter(
                id__in=list(reminded),
                start_time__gte=datetime.now(timezone.utc),
                status__in=_BOOKED_STATUSES,
            ).values_list("id", flat=True)
            with_upcoming = {reminded[str(appointment_id)] for appointment_id in upcoming}
            if len(with_upcoming) == 1:
                chosen = by_dbid[with_upcoming.pop()]
                log.info(
                    f"[inbound] {len(matches)} charts share the sending number; "
                    f"using patient {chosen.id}, the only one with a reminded "
                    "upcoming appointment"
                )
                return chosen

        chosen = by_dbid[sent[0][0]]
        log.info(
            f"[inbound] {len(matches)} charts share the sending number; "
            f"using patient {chosen.id}, the one most recently texted"
        )
        return chosen

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
