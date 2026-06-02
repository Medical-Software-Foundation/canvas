"""Send the Dexcom-connection magic link to a patient via SendGrid.

The Canvas plugin sandbox blocks ``canvas_sdk.clients.sendgrid``, so we
call the SendGrid v3 ``/mail/send`` HTTPS endpoint directly. Outbound
HTTP goes through ``canvas_sdk.utils.http.Http`` (REVIEW.md §8) which adds
metrics tracking, URL validation, and the 30s timeout ceiling.

This module is best-effort: if no API key is configured, or the patient
has no email on file, or SendGrid returns an error, the caller falls back
to displaying the link in the staff UI for manual sharing.
"""

from typing import Any, Optional

from canvas_sdk.utils.http import Http

SENDGRID_BASE_URL = "https://api.sendgrid.com"
SENDGRID_SEND_PATH = "/v3/mail/send"


class EmailDeliveryError(RuntimeError):
    """Raised when SendGrid rejects a send request."""

    def __init__(self, status_code: int, body: str) -> None:
        super().__init__(f"SendGrid error {status_code}: {body[:200]}")
        self.status_code = status_code
        self.body = body


def patient_email_address(patient: Any) -> Optional[str]:
    """Return the patient's highest-ranked *messageable* email address, or ``None``.

    Canvas stores contact points on ``Patient.telecom``; we pick the one
    with ``system='email'`` and the lowest ``rank`` (rank 1 == primary).

    The same consent gates the portal channel applies are enforced here so
    both channels fail closed identically: an email contact point is only
    used when the patient has consented, has not opted out, and the row is
    active. Without these predicates an opted-out or stale/entered-in-error
    email would still receive the magic link even though the portal Message
    is correctly suppressed.
    """
    contact = (
        patient.telecom
        .filter(
            system="email",
            has_consent=True,
            opted_out=False,
            state="active",
        )
        .order_by("rank")
        .first()
    )
    if contact is None:
        return None
    value = (contact.value or "").strip()
    return value or None


def send_magic_link_email(
    *,
    api_key: str,
    from_email: str,
    to_email: str,
    patient_first_name: str,
    link: str,
    http: Any | None = None,
) -> bool:
    """POST a templated email to SendGrid. Returns True on accepted send.

    Raises ``EmailDeliveryError`` on a non-2xx response so the caller can
    decide whether to surface a UI error or just fall back to the copyable
    link in the staff UI.
    """
    if not (api_key and from_email and to_email and link):
        raise ValueError("api_key, from_email, to_email, and link are all required")
    # ``http`` is an injection point for tests; the real runtime uses
    # ``canvas_sdk.utils.http.Http`` (REVIEW.md §8).
    if http is None:
        http = Http(SENDGRID_BASE_URL)

    greeting = patient_first_name.strip() or "there"
    subject = "Connect your Dexcom CGM to your care team"
    text_body = (
        f"Hi {greeting},\n\n"
        f"Your care team has asked you to connect your Dexcom CGM to your "
        f"patient chart so they can review your glucose trends with you.\n\n"
        f"Tap the link below on your phone (expires in 15 minutes):\n"
        f"{link}\n\n"
        f"You'll be redirected to Dexcom to log in and approve access. "
        f"No app installation is required.\n\n"
        f"If you didn't request this, you can safely ignore this email."
    )
    html_body = (
        f"<p>Hi {greeting},</p>"
        f"<p>Your care team has asked you to connect your Dexcom CGM to your "
        f"patient chart so they can review your glucose trends with you.</p>"
        f"<p><a href=\"{link}\" "
        f"style=\"display:inline-block;padding:12px 20px;background:#00853e;"
        f"color:#ffffff;border-radius:4px;text-decoration:none;\">"
        f"Connect Dexcom</a></p>"
        f"<p style=\"color:#5b6873;font-size:12px\">"
        f"This link expires in 15 minutes. If you didn't request this, you "
        f"can safely ignore this email.</p>"
    )

    payload = {
        "personalizations": [{"to": [{"email": to_email}]}],
        "from": {"email": from_email},
        "subject": subject,
        "content": [
            {"type": "text/plain", "value": text_body},
            {"type": "text/html", "value": html_body},
        ],
    }

    # SDK Http serializes ``json=`` for us and applies its own timeout/metrics.
    response = http.post(
        SENDGRID_SEND_PATH,
        json=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    if 200 <= response.status_code < 300:
        return True
    raise EmailDeliveryError(response.status_code, response.text)
