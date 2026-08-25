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
        # Every index is named explicitly, and must stay short.
        #
        # Auto-generated names are built from schema + table and then truncated
        # to Postgres's 63-byte identifier limit. This schema
        # ("canvas__appointment_reminders") plus this table name consumes 51 of
        # those bytes, leaving 12 for the discriminator — which the literal
        # "notificatio_" fills exactly. So all three indexes below truncated to
        # one identical name and only the first was ever created: verified on a
        # live instance, where this table had a single index and both the
        # created_at and campaign_type ones were silently absent. The shorter
        # sibling schema "canvas__patient_comms" had room to differ and got two.
        #
        # Django caps index names at 30 characters, so keep these terse.
        indexes = [
            Index(fields=["patient", "-created_at"], name="ar_nd_patient_created"),
            Index(fields=["-created_at"], name="ar_nd_created"),
            # For get_unresolved_senders, which filters campaign_type + status
            # and orders by -created_at. Without this the query walks the whole
            # log in created_at order filtering as it goes — and the worst case
            # is the *healthy* one: no unresolved senders means scanning every
            # row to return nothing, getting slower as the log grows.
            Index(
                fields=["campaign_type", "status", "-created_at"],
                name="ar_nd_campaign_status",
            ),
        ]
