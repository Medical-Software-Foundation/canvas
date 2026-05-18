from canvas_sdk.v1.data.base import CustomModel
from django.db.models import (
    BooleanField,
    DateTimeField,
    Index,
    JSONField,
    TextField,
)


class Pathway(CustomModel):
    """A branching clinical pathway stored as a single JSON document.

    The `definition` field carries the pathway tree (root QuestionnaireNode,
    branches with nested AND/OR/NONE conditions, terminal CustomCommand
    leaves). See `pathway-builder-ui-design.md` for the shape.

    Legacy v0.1 columns (description, recommendation, is_active) remain in
    the table because the SDK does not permit column drops; they are not
    written by v0.2 code.
    """

    title = TextField()
    description = TextField(default="")
    recommendation = TextField(default="")
    is_active = BooleanField(default=True)
    # v0.2 additions
    status = TextField(default="draft")
    definition = JSONField(default=dict)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            Index(fields=["title"]),
            Index(fields=["is_active"]),
            Index(fields=["status"]),
        ]
