from canvas_sdk.v1.data.base import CustomModel
from django.db.models import (
    DateTimeField,
    Index,
    IntegerField,
    TextField,
)


class PatientLabelAudit(CustomModel):
    """Append-only audit log for patient-label assignment changes.

    One row per transition. Fields are denormalized (label_name, label_color,
    actor_name) so the history reads correctly even after the underlying
    label or staff record is deleted.

    `via` distinguishes manual edits from rule-triggered cascades so the UI
    can disambiguate when a user wonders why a label they didn't pick was
    assigned/removed.
    """

    patient_uuid = TextField()
    label_id = IntegerField(null=True)
    label_name = TextField()
    label_color = TextField(default="blue")
    action = TextField()  # "assigned" | "removed"
    via = TextField(default="manual")  # "manual" | "rule"
    actor_id = TextField()
    actor_name = TextField()
    at = DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            Index(
                fields=["patient_uuid", "-at"],
                name="idx_patient_label_audit_at",
            ),
        ]
