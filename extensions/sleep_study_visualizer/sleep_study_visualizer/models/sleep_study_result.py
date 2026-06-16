# mypy: disable-error-code="var-annotated"
from canvas_sdk.v1.data import ModelExtension, Patient
from canvas_sdk.v1.data.base import CustomModel
from django.db.models import (
    DO_NOTHING,
    DateField,
    DateTimeField,
    DecimalField,
    ForeignKey,
    Index,
    IntegerField,
    TextField,
    UniqueConstraint,
)


class CustomPatient(Patient, ModelExtension):
    pass


class SleepStudyResult(CustomModel):
    """One row per scored sleep study, populated from a committed Sleep Study
    Result questionnaire. The source report PDF (if any) lives independently in
    Canvas as a DocumentReference and is not referenced here.
    """

    patient = ForeignKey(
        CustomPatient,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="sleep_study_results",
    )

    study_date = DateField()

    # Respiratory indices. CustomModel columns are nullable at the DB level
    # regardless, so null/blank are omitted (they have no effect - anti-pattern #9).
    ahi = DecimalField(max_digits=5, decimal_places=1)
    rdi = DecimalField(max_digits=5, decimal_places=1)
    odi = DecimalField(max_digits=5, decimal_places=1)

    # Client-asserted classification - stored verbatim, not computed.
    severity = TextField(default="")

    # Epworth Sleepiness Scale score (0-24), captured as part of the study result.
    epworth_score = IntegerField()

    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            Index(fields=["-study_date"]),
        ]
        constraints = [
            # One result per patient per study date. Backs the application-level
            # idempotency check so concurrent commits can't insert duplicates.
            UniqueConstraint(
                fields=["patient", "study_date"],
                name="unique_sleep_study_per_patient_date",
            ),
        ]
