from __future__ import annotations

from django.db.models import (
    DO_NOTHING,
    BooleanField,
    IntegerField,
    OneToOneField,
    TextField,
    UniqueConstraint,
)

from canvas_sdk.v1.data import ModelExtension, Patient
from canvas_sdk.v1.data.base import CustomModel


class PatientProxy(Patient, ModelExtension):
    """Patient proxy so custom models can relate to Canvas patients."""


class PatientNumber(CustomModel):
    """The sequential number assigned to a patient. One per patient, each number used once."""

    patient: OneToOneField[PatientProxy, PatientProxy] = OneToOneField(
        PatientProxy, to_field="dbid", on_delete=DO_NOTHING, related_name="patient_number"
    )
    number: IntegerField[int, int] = IntegerField()

    class Meta:
        constraints = [
            UniqueConstraint(fields=["number"], name="uq_patient_number_number"),
        ]


class NumberingState(CustomModel):
    """Plugin-wide flags, keyed by name. Holds whether the backfill of existing patients is done."""

    name: TextField[str, str] = TextField()
    enabled: BooleanField[bool, bool] = BooleanField(default=False)

    class Meta:
        constraints = [
            UniqueConstraint(fields=["name"], name="uq_numbering_state_name"),
        ]
