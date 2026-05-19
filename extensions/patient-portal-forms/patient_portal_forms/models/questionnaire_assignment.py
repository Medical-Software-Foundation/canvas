"""Questionnaire assignment row — one per (patient, questionnaire_name)."""

from canvas_sdk.v1.data import ModelExtension, Patient, Staff
from canvas_sdk.v1.data.base import CustomModel
from django.db.models import (
    DO_NOTHING,
    DateField,
    DateTimeField,
    ForeignKey,
    Index,
    JSONField,
    Q,
    TextField,
    UniqueConstraint,
)


class CustomPatient(Patient, ModelExtension):
    """Plugin-private handle on Patient for FK targets."""


class CustomStaff(Staff, ModelExtension):
    """Plugin-private handle on Staff for FK targets."""


class QuestionnaireAssignment(CustomModel):
    patient = ForeignKey(
        CustomPatient,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="questionnaire_assignments",
    )
    # Stored by name, not FK: publishing a new version of a questionnaire
    # mints a new id, which would orphan assignments. The name is stable
    # across versions and is the identifier the rest of the app uses.
    questionnaire_name = TextField()
    assigning_provider = ForeignKey(
        CustomStaff,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="assigned_questionnaires",
    )
    due_date = DateField()
    date_assigned = DateTimeField(auto_now_add=True)
    # NULL while the assignment is outstanding; set to the submission time
    # when the patient completes the questionnaire. Historical rows are
    # retained so a patient can take the same questionnaire repeatedly
    # (e.g. a monthly screen).
    #
    # ``null=True`` is load-bearing — the outstanding/completed lifecycle is
    # keyed off ``completed_at IS NULL`` (see the partial UniqueConstraint
    # below and every ``completed_at__isnull=True`` filter in the service).
    # Without it, Django renders the column as NOT NULL and the first
    # ``update_or_create(completed_at=None, ...)`` in ``assign()`` would
    # raise IntegrityError.
    completed_at = DateTimeField(null=True, blank=True, default=None)
    # Snapshot of the question_id / question_type / answer triples the
    # patient submitted. Populated alongside completed_at so the review
    # template can render the answers as they were at submission time
    # (independent of any later questionnaire-version changes). Empty list
    # for outstanding rows.
    submitted_answers = JSONField(default=list)

    class Meta:
        indexes = [
            Index(fields=["patient", "due_date"]),
            Index(fields=["patient", "completed_at"]),
        ]
        constraints = [
            # Only one *outstanding* assignment per (patient, questionnaire)
            # at a time. Completed rows are exempt so history can accumulate.
            UniqueConstraint(
                fields=["patient", "questionnaire_name"],
                condition=Q(completed_at__isnull=True),
                name="ppf_unique_outstanding_assignment",
            ),
        ]
