from __future__ import annotations

from datetime import datetime

from django.db.models import DateTimeField, Index, TextField, UniqueConstraint

from canvas_sdk.v1.data.base import CustomModel


class RecentPatientInteraction(CustomModel):
    """One row per (staff, patient) pair, updated on every interaction.

    Keeps the table bounded by the staff x patient cross-product. Each event
    `update_or_create`s the row keyed on (staff_id, patient_id), so the UI
    can read a single ordered query to surface what each staff member most
    recently touched.
    """

    staff_id: TextField[str, str] = TextField()
    patient_id: TextField[str, str] = TextField()
    interaction_type: TextField[str, str] = TextField()
    occurred_at: DateTimeField[datetime, datetime] = DateTimeField()

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["staff_id", "patient_id"],
                name="unique_staff_patient_interaction",
            ),
        ]
        indexes = [
            Index(fields=["staff_id", "-occurred_at"]),
            Index(fields=["occurred_at"]),
        ]
