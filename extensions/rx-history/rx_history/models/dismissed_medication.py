from django.db.models import (
    DO_NOTHING,
    DateTimeField,
    ForeignKey,
    Index,
    TextField,
    UniqueConstraint,
)

from canvas_sdk.v1.data.base import CustomModel

from rx_history.models.proxy import PatientProxy, StaffProxy


class DismissedMedication(CustomModel):
    # django-stubs is not wired into this project, so we explicitly annotate each
    # field as its descriptor type to satisfy strict mypy.
    patient: ForeignKey = ForeignKey(
        PatientProxy,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="rx_history_dismissals",
    )
    dismissed_by: ForeignKey = ForeignKey(
        StaffProxy,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="rx_history_dismissals",
    )
    drug_description: TextField = TextField()
    ndc_code: TextField = TextField(default="")
    last_fill_date: TextField = TextField(default="")
    dismissed_at: DateTimeField = DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            Index(fields=["patient", "ndc_code", "last_fill_date"]),
        ]
        constraints = [
            UniqueConstraint(
                fields=["patient", "drug_description", "ndc_code", "last_fill_date"],
                name="unique_rx_history_dismissal",
            ),
        ]
