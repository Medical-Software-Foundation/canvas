"""SavedReport — persistent storage for report configurations.

One row per saved report. The full report config (conditions, columns, etc.)
lives in `config` (JSONField). The columns lifted out of the JSON (name, etc.)
are indexed for the list view; the rest is opaque to the database and only
parsed by Python.
"""

from typing import Any

from canvas_sdk.v1.data.base import CustomModel
from django.db.models import (
    DateTimeField,
    Index,
    JSONField,
    TextField,
    UniqueConstraint,
)


class SavedReport(CustomModel):
    """A saved report configuration."""

    report_id: Any = TextField()
    name: Any = TextField()
    description: Any = TextField(default="")
    root_entity: Any = TextField()
    config: Any = JSONField(default=dict)
    created_by: Any = TextField(default="")
    created_at: Any = DateTimeField(auto_now_add=True)
    updated_at: Any = DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            UniqueConstraint(fields=["report_id"], name="unique_saved_report_id"),
        ]
        indexes = [
            Index(fields=["report_id"]),
            Index(fields=["root_entity"]),
            Index(fields=["-updated_at"]),
        ]
