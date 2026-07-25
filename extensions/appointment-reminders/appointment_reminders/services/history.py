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
            status="delivered" if result.success else "failed",
            error=result.error or "",
            content=sms_content if result.channel == "sms" else email_content,
            recipient=getattr(result, "recipient", "") or "",
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
    }


def _iso(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()
