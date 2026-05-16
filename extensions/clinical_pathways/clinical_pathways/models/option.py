from canvas_sdk.v1.data.base import CustomModel
from django.db.models import (
    DO_NOTHING,
    ForeignKey,
    Index,
    IntegerField,
    TextField,
)

from clinical_pathways.models.question import Question


class Option(CustomModel):
    """A selectable answer choice for MULTI_CHOICE or YES_NO questions.

    YES_NO questions have exactly two Option rows ("Yes" and "No"). MULTI_CHOICE
    questions have one row per choice. FREE_TEXT and NUMERIC questions have no
    Option rows.
    """

    question = ForeignKey(
        Question,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="options",
    )
    label = TextField()
    order = IntegerField(default=0)

    class Meta:
        indexes = [
            Index(fields=["question", "order"]),
        ]
