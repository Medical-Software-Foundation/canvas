"""Charge history entries — one row per charge attempt (success or failure)."""
from django.db.models import DO_NOTHING, DateTimeField, ForeignKey, IntegerField, TextField

from canvas_sdk.v1.data.base import CustomModel
from portal_membership.models.proxy import PatientProxy


class ChargeRecord(CustomModel):
    """A single billing attempt for a patient."""

    patient = ForeignKey(
        PatientProxy,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="%(app_label)s__charge_records",
    )
    charged_at = DateTimeField(auto_now_add=True)
    amount_cents = IntegerField()
    status = TextField()  # "succeeded" | "failed"
    description = TextField()
    discount_code = TextField(default="")

    class Meta:
        ordering = ["-charged_at"]
