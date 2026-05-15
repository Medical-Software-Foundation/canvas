from __future__ import annotations

from datetime import date, datetime

from django.db.models import (
    BooleanField,
    DateField,
    DateTimeField,
    DO_NOTHING,
    ForeignKey,
    Index,
    IntegerField,
    TextField,
)

from canvas_sdk.v1.data.base import CustomModel
from canvas_sdk.v1.data.patient import Patient


class Hospitalization(CustomModel):
    """A structured hospitalization record linked to a patient."""

    patient: ForeignKey[Patient, Patient] = ForeignKey(
        Patient,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="+",
    )
    admission_date: DateField[date, date] = DateField()
    discharge_date: DateField[date | None, date | None] = DateField(null=True, blank=True)
    hospital_name: TextField[str, str] = TextField()
    reason_for_admission: TextField[str, str] = TextField()
    principal_diagnosis: TextField[str, str] = TextField(blank=True, default="")
    icu_stay: BooleanField[bool, bool] = BooleanField(default=False)
    icu_duration_days: IntegerField[int | None, int | None] = IntegerField(null=True, blank=True)
    discharge_disposition: TextField[str, str] = TextField(blank=True, default="")
    readmission_within_30_days: BooleanField[bool, bool] = BooleanField(default=False)
    treating_physician: TextField[str, str] = TextField(blank=True, default="")
    notes: TextField[str, str] = TextField(blank=True, default="")
    created_at: DateTimeField[str | datetime, datetime] = DateTimeField(auto_now_add=True)
    updated_at: DateTimeField[str | datetime, datetime] = DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            Index(fields=["admission_date"]),
        ]

    @property
    def length_of_stay_days(self) -> int | None:
        """Return the number of days between admission and discharge, if both are set."""
        if self.admission_date and self.discharge_date:
            return (self.discharge_date - self.admission_date).days
        return None
