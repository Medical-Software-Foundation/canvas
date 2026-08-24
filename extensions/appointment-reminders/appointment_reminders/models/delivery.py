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
    # Nullable for one case only: an inbound reply whose sender matched no
    # patient (campaign_type="inbound_response", status="unresolved_sender").
    # Without it that event is unrecordable, and an unrecorded one is
    # indistinguishable from the patient never replying at all.
    #
    # Costs no migration: Canvas does not create `not null` constraints on
    # CustomModels ("Unsupported constraints: not null"), so the column has
    # always been nullable in Postgres and this only aligns the ORM with it.
    patient = ForeignKey(
        CustomPatient,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="notification_deliveries",
        null=True,
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
