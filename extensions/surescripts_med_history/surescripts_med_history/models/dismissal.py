from django.db.models import (
    DO_NOTHING,
    DateTimeField,
    ForeignKey,
    TextField,
    UniqueConstraint,
)

from canvas_sdk.v1.data.base import CustomModel

from surescripts_med_history.models.proxy import PatientProxy


class MedicationDismissal(CustomModel):
    """A user-dismissed Surescripts medication group for a patient.

    group_key matches the dedup key used by the modal (NDC if available,
    drug_description otherwise) so the dismissal applies to the same
    grouping the user sees. Auto-cleared by the action button when:
      - the dismissed medication is now matched against an active med, or
      - a fill arrives with a date after the dismissal.
    """

    patient = ForeignKey(
        PatientProxy,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="%(app_label)s__medication_dismissals",
    )
    group_key = TextField()
    drug_description = TextField(default="")
    dismissed_by = TextField(default="")
    dismissed_by_id = TextField(default="")
    dismissed_at = DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["patient", "group_key"],
                name="uq_med_dismissal_patient_group",
            ),
        ]
