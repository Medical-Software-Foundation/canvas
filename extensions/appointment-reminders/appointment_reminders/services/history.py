"""Notification delivery history — persisted as CustomModel rows."""
from datetime import datetime, timezone

from canvas_sdk.v1.data.patient import Patient
from logger import log

from appointment_reminders.models.delivery import (
    CustomPatient,
    NotificationDelivery,
)


def log_delivery(
    appointment_id: str,
    patient_id: str,
    campaign_type: str,
    results: list,
    sms_content: str = "",
    email_content: str = "",
) -> None:
    """Insert one NotificationDelivery row per DeliveryResult.

    `results` is a list of DeliveryResult-like objects with `channel`,
    `success`, `error`, and optionally `recipient` attributes.
    """
    if not results:
        return

    try:
        patient = CustomPatient.objects.get(id=patient_id)
    except Patient.DoesNotExist:
        log.warning(
            f"[notify] log_delivery skipped — patient {patient_id} not found"
        )
        return

    for result in results:
        NotificationDelivery.objects.create(
            patient=patient,
            appointment_id=appointment_id or "",
            campaign_type=campaign_type,
            channel=result.channel,
            # "accepted", not "delivered": a successful result means Twilio or
            # SendGrid took the request, nothing more. No status callback is
            # consumed, so the plugin never learns whether the carrier delivered
            # it. Saying "delivered" asserted something we cannot know, and it
            # misreported a message that Twilio accepted and then dropped.
            status="accepted" if result.success else "failed",
            error=result.error or "",
            content=sms_content if result.channel == "sms" else email_content,
            recipient=getattr(result, "recipient", "") or "",
            message_id=getattr(result, "message_id", "") or "",
        )


def log_inbound_response(
    patient_id: str,
    appointment_id: str,
    status: str,
    body: str,
    from_number: str,
) -> None:
    """Record a patient's inbound SMS reply (confirm/decline/unrecognized).

    Stored as a ``NotificationDelivery`` row with campaign_type
    ``inbound_response`` so it surfaces in the same activity log / patient
    history as outbound sends — and powers the "needs outreach" view.
    """
    try:
        patient = CustomPatient.objects.get(id=patient_id)
    except Patient.DoesNotExist:
        log.warning(
            f"[inbound] log_inbound_response skipped — patient {patient_id} not found"
        )
        return

    NotificationDelivery.objects.create(
        patient=patient,
        appointment_id=appointment_id or "",
        campaign_type="inbound_response",
        channel="sms",
        status=status,
        error="",
        content=body or "",
        recipient=from_number or "",
    )


def log_unresolved_sender(body: str, from_number: str) -> None:
    """Record a verified inbound reply whose sender matched no patient.

    Without this the event leaves no trace: ``inbound()`` returns 200 and the
    appointment simply stays unconfirmed, which ops reads as the patient never
    replying. That is the opposite of what happened — the patient did reply, and
    the number they replied from is not on any chart.

    Written with ``patient=None``, the one case where that is allowed. Rows are
    read back by ``get_unresolved_senders`` rather than the per-patient history,
    which is keyed on a patient by definition.
    """
    NotificationDelivery.objects.create(
        patient=None,
        appointment_id="",
        campaign_type="inbound_response",
        channel="sms",
        status="unresolved_sender",
        error="",
        content=body or "",
        recipient=from_number or "",
    )


def get_unresolved_senders(limit: int = 100) -> list[dict]:
    """Return recent replies that matched no patient, newest first."""
    rows = (
        NotificationDelivery.objects.filter(
            campaign_type="inbound_response",
            status="unresolved_sender",
        )
        .order_by("-created_at")[:limit]
    )
    return [_row_to_dict("", row) for row in rows]


def get_patient_history(patient_id: str, limit: int = 100) -> list[dict]:
    """Return the most recent deliveries for a patient, newest first."""
    rows = (
        NotificationDelivery.objects.filter(patient__id=patient_id)
        .order_by("-created_at")[:limit]
    )
    return [_row_to_dict(patient_id, row) for row in rows]


def _row_to_dict(patient_id: str, row: NotificationDelivery) -> dict:
    return {
        "timestamp": _iso(row.created_at),
        "appointment_id": row.appointment_id,
        "patient_id": patient_id,
        "campaign_type": row.campaign_type,
        "channel": row.channel,
        "status": row.status,
        "error": row.error,
        "content": row.content,
        "recipient": row.recipient,
        "message_id": row.message_id or "",
        "status_label": _status_label(row.status),
        "campaign_label": _campaign_label(row.campaign_type),
    }


# Legacy rows say "delivered", which never meant more than "accepted" either.
# Both render the same way so history reads consistently and neither overclaims.
_STATUS_LABELS = {
    "accepted": "Sent",
    "delivered": "Sent",
    "failed": "Failed",
    "declined": "Declined",
    "confirmed": "Confirmed",
    "opted_out": "Opted out",
    "opted_in": "Opted back in",
    "unresolved_sender": "Unmatched number",
}


# Raw keys render badly when merely capitalized — "inbound_response" became
# "Inbound_response" in the patient panel. Names match the admin app's campaign
# cards so an operator sees the same wording in both places.
_CAMPAIGN_LABELS = {
    "confirmation": "Booking acknowledgement",
    "reminder": "Reminder",
    "telehealth": "Telehealth join",
    "noshow": "No-show",
    "cancellation": "Cancellation",
    "inbound_response": "Patient reply",
    "message_notification": "Message",
}


def _campaign_label(campaign_type: str) -> str:
    """A human label for a campaign type, falling back to a tidied raw value."""
    if campaign_type in _CAMPAIGN_LABELS:
        return _CAMPAIGN_LABELS[campaign_type]
    tidied = (campaign_type or "").replace("_", " ").strip()
    return tidied[:1].upper() + tidied[1:] if tidied else ""


def _status_label(status: str) -> str:
    """A human label for a stored status, falling back to the raw value."""
    if status in _STATUS_LABELS:
        return _STATUS_LABELS[status]
    # Composite inbound statuses like "opted_out+declined".
    parts = [_STATUS_LABELS.get(p, p) for p in (status or "").split("+") if p]
    return " + ".join(parts) if parts else (status or "")


def _iso(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()
