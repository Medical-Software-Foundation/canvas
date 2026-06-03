"""Pointer from (patient, calendar date) to the bundled portal-form note.

The submit endpoint groups every questionnaire a patient submits on a given
day into one Patient Portal Form note. This model holds the pointer to that
day's note. When the existing note becomes unusable (locked / relocked /
deleted / cancelled), the row is updated in place to point at a fresh note
UUID — the unique constraint keeps "one pointer per day per patient" as a
schema invariant.

Bundling only happens when a proper "Patient Portal Form" note type is
configured in the instance. When the plugin falls back to a Data Import note
type, no row is written here: DATA notes are treated as one-shot writes.
"""

from canvas_sdk.v1.data.base import CustomModel
from django.db.models import (
    DO_NOTHING,
    DateField,
    ForeignKey,
    Index,
    TextField,
    UniqueConstraint,
)

from patient_portal_forms.models.questionnaire_assignment import CustomPatient


class PatientDailyNote(CustomModel):
    patient = ForeignKey(
        CustomPatient,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="daily_portal_form_notes",
    )
    date = DateField()
    # Stored as TextField holding the Note UUID (Note.id) — same rationale as
    # other cross-namespace references: keep it simple and avoid an FK into
    # SDK data that already lives in a separate table.
    note_uuid = TextField()

    class Meta:
        indexes = [
            Index(fields=["patient", "date"]),
        ]
        constraints = [
            UniqueConstraint(
                fields=["patient", "date"],
                name="ppf_unique_patient_daily_note",
            ),
        ]
