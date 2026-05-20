from canvas_sdk.v1.data import ModelExtension, Staff
from canvas_sdk.v1.data.base import CustomModel
from django.db.models import (
    DO_NOTHING,
    DateTimeField,
    ForeignKey,
    Index,
    JSONField,
    TextField,
)


class CustomStaff(Staff, ModelExtension):
    pass


class SearchFeedback(CustomModel):
    """Stores per-turn feedback for AI chart search responses."""

    feedback_id = TextField()
    patient_id = TextField()
    staff = ForeignKey(
        CustomStaff,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="%(app_label)s__search_feedbacks",
    )
    query = TextField()
    answer_summary = TextField()
    answer_key_findings = JSONField(default=list)
    rating = TextField()
    comment = TextField()
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            Index(fields=["feedback_id"]),
            Index(fields=["patient_id"]),
            Index(fields=["rating"]),
            Index(fields=["created_at"]),
        ]
