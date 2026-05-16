from canvas_sdk.v1.data.base import CustomModel
from django.db.models import (
    DO_NOTHING,
    BooleanField,
    ForeignKey,
    Index,
    IntegerField,
    TextField,
)

from clinical_pathways.models.segment import Segment


class ResponseType:
    """Allowed answer-input types for a Question.

    Stored as the raw string value; not a Django enum field so that the SDK's
    CustomModel runner can persist this as a plain TextField without schema
    introspection on a choices enum.
    """

    YES_NO = "yes_no"
    MULTI_CHOICE = "multi"
    FREE_TEXT = "free_text"
    NUMERIC = "numeric"

    ALL = (YES_NO, MULTI_CHOICE, FREE_TEXT, NUMERIC)


class Question(CustomModel):
    """A single question within a segment."""

    segment = ForeignKey(
        Segment,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="questions",
    )
    text = TextField()
    response_type = TextField(default=ResponseType.FREE_TEXT)
    order = IntegerField(default=0)
    required = BooleanField(default=True)

    class Meta:
        indexes = [
            Index(fields=["segment", "order"]),
        ]
