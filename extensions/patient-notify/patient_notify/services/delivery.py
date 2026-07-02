"""Patient notification delivery via direct SMS and email."""
import re
from dataclasses import dataclass

import requests
from canvas_sdk.effects import Effect
from canvas_sdk.v1.data.patient import Patient
from logger import log


_TWILIO_ERROR_MAP: dict[int, str] = {
    20003: "Twilio credentials rejected - check Account SID and Auth Token in plugin secrets",
    21210: "Invalid phone number format",
    21211: "Invalid phone number format",
    21610: "Recipient has opted out of messages from this number",
    21612: "This phone number is unreachable or blocked",
    21614: "This phone number cannot receive SMS (landline or VoIP)",
    30006: "Landline or unreachable phone number",
    30007: "Message filtered by carrier or Twilio",
}


@dataclass
class DeliveryResult:
    """Result of a delivery attempt."""

    success: bool
    channel: str
    error: str | None = None
    error_code: int | None = None
    message_id: str | None = None


def _normalize_phone_e164(raw: str) -> str | None:
    """Normalize a US phone number to E.164 format.

    Strips non-digit characters, prepends +1 if needed.
    Returns None if the result is not a valid 11-digit US number.
    """
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 10:
        digits = "1" + digits
    if len(digits) == 11 and digits[0] == "1":
        return "+" + digits
    return None


def _get_patient_contacts(patient: Patient) -> tuple[list[str], list[str]]:
    """Extract all consented active phones and emails from patient telecom."""
    phones: list[str] = []
    emails: list[str] = []
    for contact in patient.telecom.filter(
        system__in=["phone", "email"],
        has_consent=True,
        state="active",
    ):
        if contact.system == "phone":
            phones.append(contact.value)
        elif contact.system == "email":
            emails.append(contact.value)
    return phones, emails


def _send_sms(
    to_phone: str,
    body: str,
    account_sid: str,
    auth_token: str,
    from_number: str,
) -> DeliveryResult:
    """Send SMS via Twilio REST API."""
    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    try:
        response = requests.post(
            url,
            data={"To": to_phone, "From": from_number, "Body": body},
            auth=(account_sid, auth_token),
            timeout=10,
        )
        if response.ok:
            sid = response.json().get("sid", "")
            return DeliveryResult(success=True, channel="sms", message_id=sid)

        try:
            body_json = response.json()
            code = body_json.get("code")
            friendly = _TWILIO_ERROR_MAP.get(
                code, body_json.get("message", "Unknown error")
            )
            return DeliveryResult(
                success=False, channel="sms", error=friendly, error_code=code,
            )
        except Exception:
            return DeliveryResult(
                success=False, channel="sms", error=f"HTTP {response.status_code}",
            )
    except Exception as e:
        return DeliveryResult(success=False, channel="sms", error=str(e))


def _escape_html(text: str) -> str:
    """Escape the five standard XML entities."""
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )


def _plaintext_to_html(text: str) -> str:
    """Convert plain text to simple HTML for email rendering."""
    if "<p>" in text or "<br" in text:
        return text
    escaped = _escape_html(text)
    paragraphs = escaped.split("\n\n")
    return "".join(f"<p>{p.replace(chr(10), '<br>')}</p>" for p in paragraphs)


def _newlines_to_br(text: str) -> str:
    """Convert newlines to <br> for email rendering if no block-level HTML is present."""
    if "<p>" in text or "<p " in text or "<br" in text or "<div>" in text or "<div " in text:
        return text
    return text.replace("\n", "<br>")


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
    payload = {
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
    except Exception as e:
        return DeliveryResult(success=False, channel="email", error=str(e))


def _has_direct_sms_keys(secrets: dict[str, str]) -> bool:
    """Check if Twilio credentials are configured."""
    return all(
        secrets.get(k)
        for k in ("twilio-account-sid", "twilio-auth-token", "twilio-phone-number")
    )


def _has_direct_email_keys(secrets: dict[str, str]) -> bool:
    """Check if SendGrid credentials are configured."""
    return all(secrets.get(k) for k in ("sendgrid-api-key", "sendgrid-from-email"))


# Email subject lines per campaign type
_EMAIL_SUBJECTS = {
    "confirmation": "Appointment Confirmation",
    "reminder": "Appointment Reminder",
    "noshow": "We Missed You",
    "cancellation": "Appointment Cancelled",
}


def deliver_to_patient(
    patient: Patient,
    sms_content: str,
    email_content: str,
    channels: list[str],
    campaign_type: str,
    secrets: dict[str, str],
) -> tuple[list[Effect], list[DeliveryResult]]:
    """Deliver a notification to a patient via SMS and email.

    Sends to all consented active contacts. Logs a descriptive skip reason
    when delivery is not possible for a given channel.

    Returns a tuple of (effects to apply, delivery results for logging).
    """
    phones, emails = _get_patient_contacts(patient)
    has_sms_keys = _has_direct_sms_keys(secrets)
    has_email_keys = _has_direct_email_keys(secrets)
    effects: list[Effect] = []
    results: list[DeliveryResult] = []

    if "sms" in channels:
        if not phones:
            results.append(DeliveryResult(
                success=False, channel="sms",
                error="no consented active phone number on file",
            ))
        elif not has_sms_keys:
            results.append(DeliveryResult(
                success=False, channel="sms",
                error="Twilio credentials not configured",
            ))
        else:
            for raw_phone in phones:
                normalized = _normalize_phone_e164(raw_phone)
                if not normalized:
                    results.append(DeliveryResult(
                        success=False, channel="sms",
                        error=f"phone number {raw_phone} could not be normalized to E.164 format",
                    ))
                    continue

                result = _send_sms(
                    to_phone=normalized,
                    body=sms_content,
                    account_sid=secrets["twilio-account-sid"],
                    auth_token=secrets["twilio-auth-token"],
                    from_number=secrets["twilio-phone-number"],
                )
                results.append(result)
                if result.success:
                    log.info(f"[delivery] SMS sent for {campaign_type} to patient {patient.id}")
                else:
                    log.warning(
                        f"[delivery] SMS failed for {campaign_type} to patient {patient.id}, "
                        f"error: {result.error}"
                    )

    if "email" in channels:
        if not emails:
            results.append(DeliveryResult(
                success=False, channel="email",
                error="no consented active email address on file",
            ))
        elif not has_email_keys:
            results.append(DeliveryResult(
                success=False, channel="email",
                error="SendGrid credentials not configured",
            ))
        else:
            subject = _EMAIL_SUBJECTS.get(campaign_type, "Notification")
            for addr in emails:
                result = _send_email(
                    to_email=addr,
                    subject=subject,
                    html_body=_newlines_to_br(email_content),
                    api_key=secrets["sendgrid-api-key"],
                    from_email=secrets["sendgrid-from-email"],
                )
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

    return effects, results
