from canvas_sdk.v1.data import Patient
from canvas_sdk.v1.data.base import CustomModel, ModelExtension
from django.db.models import DO_NOTHING, ForeignKey, UniqueConstraint

from patient_tags.models.label import Label


class PatientProxy(Patient, ModelExtension):
    """Proxy onto the SDK Patient model so PatientLabel can foreign-key to it."""

    pass


class PatientLabel(CustomModel):
    """Assignment of a Label to a Patient. One row per (patient, label) pair."""

    patient = ForeignKey(
        PatientProxy,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="patient_labels",
    )
    label = ForeignKey(
        Label,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="assignments",
    )

    class Meta:
        constraints = [
            UniqueConstraint(fields=["patient", "label"], name="unique_patient_label"),
        ]
