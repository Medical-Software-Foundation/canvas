from canvas_sdk.v1.data.base import CustomModel
from django.db.models import (
    BooleanField,
    DateTimeField,
    Index,
    JSONField,
    TextField,
)


class Pathway(CustomModel):
    """A clinical pathway stored as a single JSON document.

    The `definition` field carries the v3 schema: a flat `steps[]` list where
    each step references a (questionnaire, question) pair and carries its own
    `rules[]` (each with per-condition `and`/`or` connectors) plus an
    `otherwise` target, alongside a `recommendations[]` list of terminal
    custom commands. See SPEC.md for the full JSON shape.

    The `recommendation` column is a vestigial v0.1 field that remains in the
    table because the SDK does not permit column drops; it is never read or
    written by current code.
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
