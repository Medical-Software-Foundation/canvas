"""Audit log row for each SMS/email delivery attempt."""

from canvas_sdk.v1.data import ModelExtension, Patient
from canvas_sdk.v1.data.base import CustomModel
from django.db.models import (
    DO_NOTHING,
    DateTimeField,
    ForeignKey,
    Index,
    TextField,
)


class CustomPatient(Patient, ModelExtension):
    """Plugin-private handle on Patient for FK targets."""


class NotificationDelivery(CustomModel):
    patient = ForeignKey(
        CustomPatient,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="notification_deliveries",
    )
    # Appointment is optional — direct messages and some form reminders
    # are not tied to one. Stored as the UUID string rather than an FK so
    # the column is safely absent for those rows.
    appointment_id = TextField(default="")
    campaign_type = TextField()
    channel = TextField()
    status = TextField()
    error = TextField(default="")
    content = TextField(default="")
    recipient = TextField(default="")
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            Index(fields=["patient", "-created_at"]),
            Index(fields=["-created_at"]),
        ]
