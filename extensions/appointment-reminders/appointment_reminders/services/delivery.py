"""Patient notification delivery via direct SMS/email with appointment metadata tracking."""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests
from canvas_sdk.effects import Effect
from canvas_sdk.effects.appointments_metadata import AppointmentsMetadata
from canvas_sdk.v1.data.patient import Patient
from logger import log


@dataclass
class DeliveryResult:
    """Result of a delivery attempt."""

    success: bool
    channel: str
    error: str | None = None
    message_id: str | None = None
    recipient: str = ""


def _normalize_phone(number: str) -> str:
    """Normalize a phone number to E.164 format for Twilio."""
    digits = "".join(ch for ch in number if ch.isdigit())
    if not digits:
        return number
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits[0] == "1":
        return "+" + digits
    if not number.startswith("+"):
        return "+" + digits
    return number


def _get_patient_contacts(patient: Patient) -> tuple[str | None, str | None]:
    """Return the primary phone and email this patient can receive automated
    messages on, lowest-rank first.

    Phone (SMS) requires explicit ``has_consent=True`` — TCPA compliance.
    The Canvas patient-chart UI exposes a "Has consent to send messages"
    toggle on phone numbers so practices can record this affirmatively.
    A patient who replies STOP has ``has_consent`` cleared by this plugin's
    inbound webhook (``services/consent.py``), and may separately carry
    ``opted_out=True`` from Canvas's native handler or a staff edit; either
    one suppresses SMS here. Texting them again is both a TCPA violation and
    will be rejected by Twilio (error 21610).

    Email consent is implicit. The Canvas UI does NOT expose a per-email
    consent toggle — adding an email to the chart is the consent gesture
    (the UI text reads "This email will be used so [practice] can
    communicate with [patient] ... messages from the patient chart, lab
    reports after review, campaign outreach and more"). Filtering emails
    by ``has_consent=True`` would always reject them because the field
    has no path to be set affirmatively. We only honor ``opted_out=True``
    as an unsubscribe signal.
    """
    # Filter the prefetched `telecom` in Python (rank/has_consent/opted_out are
    # non-nullable, so this exactly matches the prior ORM filters) so the
    # reminder-cron prefetch pays off instead of re-querying per send.
    contacts = sorted(
        (c for c in patient.telecom.all() if not c.opted_out),
        key=lambda c: c.rank,
    )
    phone_contact = next(
        (c for c in contacts if c.system == "phone" and c.has_consent), None
    )
    email_contact = next((c for c in contacts if c.system == "email"), None)
    phone = _normalize_phone(phone_contact.value) if phone_contact else None
    email = email_contact.value if email_contact else None
    return phone, email


def _twilio_auth(secrets: dict[str, str]) -> tuple[str, str]:
    """Resolve the Twilio Basic-Auth (username, password) pair.

    Prefer a revocable **API Key** (``twilio-api-key-sid`` + ``twilio-api-key-secret``)
    so the master Auth Token need not be stored in the plugin — an API key can be
    revoked independently and scoped away from the rest of the Twilio account. Fall
    back to (Account SID, Auth Token) when no API key is configured. Either way the
    request URL still uses the Account SID (see ``_send_sms``).
    """
    key_sid = (secrets.get("twilio-api-key-sid") or "").strip()
    key_secret = (secrets.get("twilio-api-key-secret") or "").strip()
    if key_sid and key_secret:
        return (key_sid, key_secret)
    return (secrets.get("twilio-account-sid", ""), secrets.get("twilio-auth-token", ""))


def _send_sms(
    to_phone: str,
    body: str,
    account_sid: str,
    auth: tuple[str, str],
    from_number: str,
) -> DeliveryResult:
    """Send SMS via Twilio REST API.

    ``account_sid`` is used only to build the request URL; ``auth`` is the
    Basic-Auth pair from ``_twilio_auth`` — either an API key or the master token.
    """
    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    try:
        response = requests.post(
            url,
            data={"To": to_phone, "From": from_number, "Body": body},
            auth=auth,
            timeout=10,
        )
        response.raise_for_status()
        sid = response.json().get("sid", "")
        return DeliveryResult(success=True, channel="sms", message_id=sid)
    except requests.exceptions.HTTPError as e:
        error_msg = _parse_twilio_error(e.response)
        return DeliveryResult(success=False, channel="sms", error=error_msg)
    except requests.exceptions.RequestException as e:
        # Only catch network/HTTP transport errors — let programming bugs
        # (e.g. response parsing) surface to Sentry instead of masquerading
        # as carrier failures.
        return DeliveryResult(success=False, channel="sms", error=str(e))


# Twilio error codes with user-friendly messages
_TWILIO_ERROR_MESSAGES = {
    21610: "Recipient has opted out of SMS (replied STOP)",
    21611: "Recipient has opted out of SMS",
    21612: "Recipient cannot receive SMS (landline or invalid number)",
    21614: "Invalid phone number",
    21408: "Permission denied — check Twilio account geo permissions",
    21211: "Invalid phone number format",
    30004: "Message blocked — recipient has opted out",
    30005: "Unknown destination number",
    30006: "Landline or unreachable number",
    30007: "Message filtered by carrier",
    30008: "Unknown error from carrier",
}


def _parse_twilio_error(response: requests.Response | None) -> str:
    """Extract a user-friendly error message from a Twilio error response."""
    if response is None:
        return "SMS delivery failed"
    try:
        data = response.json()
        code = data.get("code")
        if code and code in _TWILIO_ERROR_MESSAGES:
            return _TWILIO_ERROR_MESSAGES[code]
        # Fall back to Twilio's own message if available
        twilio_msg = data.get("message", "")
        if twilio_msg:
            return f"SMS failed: {twilio_msg}"
    except Exception:
        pass
    return f"SMS failed (HTTP {response.status_code})"


def _send_email(
    to_email: str,
    subject: str,
    html_body: str,
    api_key: str,
    from_email: str,
) -> DeliveryResult:
    """Send email via SendGrid v3 API."""
    url = "https://api.sendgrid.com/v3/mail/send"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "personalizations": [{"to": [{"email": to_email}]}],
        "from": {"email": from_email},
        "subject": subject,
        "content": [{"type": "text/html", "value": html_body}],
    }
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        msg_id = response.headers.get("X-Message-Id", "")
        return DeliveryResult(success=True, channel="email", message_id=msg_id)
    except requests.exceptions.RequestException as e:
        # Catch transport errors only; let unexpected bugs raise to Sentry.
        return DeliveryResult(success=False, channel="email", error=str(e))


def _has_direct_sms_keys(secrets: dict[str, str]) -> bool:
    """Check if Twilio credentials are configured.

    Requires an Account SID + from-number, plus a valid auth path: either an
    API key pair (preferred) or the master Auth Token.
    """
    if not (secrets.get("twilio-account-sid") and secrets.get("twilio-phone-number")):
        return False
    has_api_key = bool(
        (secrets.get("twilio-api-key-sid") or "").strip()
        and (secrets.get("twilio-api-key-secret") or "").strip()
    )
    return has_api_key or bool(secrets.get("twilio-auth-token"))


def _has_direct_email_keys(secrets: dict[str, str]) -> bool:
    """Check if SendGrid credentials are configured."""
    return all(secrets.get(k) for k in ("sendgrid-api-key", "sendgrid-from-email"))


_TESTING_TRUE = {"1", "true", "yes", "on"}


def is_testing_mode_active(secrets: dict[str, str]) -> bool:
    """Global safe-launch/troubleshooting gate.

    When ``TESTING_MODE`` is on, ALL outbound is suppressed unless BOTH the
    patient AND the recipient address are on their allowlists — a hard, fail-closed
    restriction so the plugin can be exercised on any instance (incl. prod) without
    messaging the general population. Empty/absent allowlists ⇒ nothing sends.
    """
    return (secrets.get("TESTING_MODE") or "").strip().lower() in _TESTING_TRUE


def _csv_set(raw: str | None) -> set[str]:
    """Parse a comma-separated secret into a set of trimmed, non-empty tokens."""
    return {item.strip() for item in (raw or "").split(",") if item.strip()}


def _patient_allowlisted(patient: Patient, allow: set[str]) -> bool:
    """True if the patient matches the testing-mode patient allowlist.

    Matches against any of the patient's identifiers (key/id/dbid) so whichever
    value an operator pastes from the chart works. Empty allowlist ⇒ False.
    """
    if not allow:
        return False
    candidates = {str(getattr(patient, "id", "")), str(getattr(patient, "dbid", ""))}
    key = getattr(patient, "key", None)
    if key:
        candidates.add(str(key))
    candidates.discard("")
    return bool(candidates & allow)


def _recipient_allowlisted(value: str, channel: str, allow: set[str]) -> bool:
    """True if the outbound address is on the testing-mode recipient allowlist.

    Phones are compared in normalized E.164 form; emails case-insensitively. The
    allowlist may mix phones and emails; only the entries matching the channel are
    considered. Empty allowlist ⇒ False.
    """
    if not allow:
        return False
    if channel == "sms":
        target = _normalize_phone(value)
        return any(_normalize_phone(a) == target for a in allow if "@" not in a)
    return value.strip().lower() in {a.strip().lower() for a in allow if "@" in a}


# Email subject lines per campaign type
_EMAIL_SUBJECTS = {
    "confirmation": "Appointment Confirmation",
    "reminder": "Appointment Reminder",
    "noshow": "We Missed You",
    "cancellation": "Appointment Cancelled",
}


def _build_metadata_effects(
    appointment_id: str,
    campaign_type: str,
    results: list[DeliveryResult],
) -> list[Effect]:
    """Create AppointmentsMetadata effects to record delivery results."""
    effects: list[Effect] = []
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for result in results:
        key = f"notify:{campaign_type}:{result.channel}"
        if result.success:
            status = "delivered"
        elif result.error and result.error.startswith("skipped:"):
            status = "skipped"
        else:
            status = "failed"
        detail = result.error or result.message_id or ""
        # Value format: status|timestamp|detail (max 256 chars)
        value = f"{status}|{ts}|{detail}"[:256]
        metadata = AppointmentsMetadata(appointment_id=appointment_id, key=key)
        effects.append(metadata.upsert(value=value))
    return effects


def deliver_to_patient(
    patient: Patient,
    sms_content: str,
    email_content: str,
    channels: list[str],
    campaign_type: str,
    secrets: dict[str, str],
    appointment_id: str = "",
    from_number: str = "",
) -> tuple[list[Effect], list[DeliveryResult]]:
    """Deliver a notification to a patient via SMS/email.

    Sends via configured channels (Twilio SMS, SendGrid email).
    Records delivery results as appointment metadata.

    ``from_number`` overrides the outbound SMS sender (e.g. a per-business-line
    number). When empty, the global ``twilio-phone-number`` secret is used.

    Returns a tuple of (effects to apply, delivery results for logging).
    """
    phone, email = _get_patient_contacts(patient)
    has_sms_keys = _has_direct_sms_keys(secrets)
    has_email_keys = _has_direct_email_keys(secrets)
    results: list[DeliveryResult] = []

    # Testing-mode gate: when active, a send requires the patient AND the recipient
    # address to both be allowlisted (fail-closed). Resolved once per delivery.
    testing_mode = is_testing_mode_active(secrets)
    tm_recipients = _csv_set(secrets.get("TESTING_MODE_RECIPIENTS"))
    patient_ok = (
        _patient_allowlisted(patient, _csv_set(secrets.get("TESTING_MODE_PATIENTS")))
        if testing_mode
        else True
    )

    if "sms" in channels:
        if not has_sms_keys:
            reason = "skipped:twilio_keys_not_configured"
            log.warning(f"[delivery] {reason} for {campaign_type}")
            results.append(DeliveryResult(success=False, channel="sms", error=reason))
        elif not phone:
            reason = "skipped:no_phone_on_file"
            log.warning(f"[delivery] {reason} for patient {patient.id}, {campaign_type}")
            results.append(DeliveryResult(success=False, channel="sms", error=reason))
        elif testing_mode and not (patient_ok and _recipient_allowlisted(phone, "sms", tm_recipients)):
            reason = "skipped:testing_mode"
            log.warning(f"[delivery] {reason} — patient/recipient not allowlisted, {campaign_type}")
            results.append(DeliveryResult(success=False, channel="sms", error=reason))
        else:
            result = _send_sms(
                to_phone=phone,
                body=sms_content,
                account_sid=secrets["twilio-account-sid"],
                auth=_twilio_auth(secrets),
                from_number=from_number or secrets["twilio-phone-number"],
            )
            result.recipient = phone
            results.append(result)
            if result.success:
                log.info(f"[delivery] SMS sent for {campaign_type} to patient {patient.id}")
            else:
                log.warning(
                    f"[delivery] SMS failed for {campaign_type} to patient {patient.id}, "
                    f"error: {result.error}"
                )

    if "email" in channels:
        if not has_email_keys:
            reason = "skipped:sendgrid_keys_not_configured"
            log.warning(f"[delivery] {reason} for {campaign_type}")
            results.append(DeliveryResult(success=False, channel="email", error=reason))
        elif not email:
            reason = "skipped:no_email_on_file"
            log.warning(f"[delivery] {reason} for patient {patient.id}, {campaign_type}")
            results.append(DeliveryResult(success=False, channel="email", error=reason))
        elif testing_mode and not (patient_ok and _recipient_allowlisted(email, "email", tm_recipients)):
            reason = "skipped:testing_mode"
            log.warning(f"[delivery] {reason} — patient/recipient not allowlisted, {campaign_type}")
            results.append(DeliveryResult(success=False, channel="email", error=reason))
        else:
            subject = _EMAIL_SUBJECTS.get(campaign_type, "Notification")
            result = _send_email(
                to_email=email,
                subject=subject,
                html_body=email_content,
                api_key=secrets["sendgrid-api-key"],
                from_email=secrets["sendgrid-from-email"],
            )
            result.recipient = email
            results.append(result)
            if result.success:
                log.info(
                    f"[delivery] Email sent for {campaign_type} to patient {patient.id}"
                )
            else:
                log.warning(
                    f"[delivery] Email failed for {campaign_type} to patient {patient.id}, "
                    f"error: {result.error}"
                )

    # Save delivery results as appointment metadata (only when appointment_id is present)
    effects = _build_metadata_effects(appointment_id, campaign_type, results) if appointment_id else []

    return effects, results
