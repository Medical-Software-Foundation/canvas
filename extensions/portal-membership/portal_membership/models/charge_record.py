"""Charge history entries — one row per charge attempt (success or failure)."""
from django.db.models import DateTimeField, IntegerField, TextField

from canvas_sdk.v1.data.base import CustomModel


class ChargeRecord(CustomModel):
    """A single billing attempt for a patient."""

    patient_id = TextField(db_index=True)
    charged_at = DateTimeField(auto_now_add=True)
    amount_cents = IntegerField()
    status = TextField()  # "succeeded" | "failed"
    description = TextField()
    discount_code = TextField(default="")

    class Meta:
        ordering = ["-charged_at"]
