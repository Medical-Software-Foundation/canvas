from typing import Any

from django.db.models import DO_NOTHING, DateTimeField, OneToOneField, TextField

from canvas_sdk.v1.data.base import CustomModel
from custom_visit_notes.models.proxy import NoteProxy


class VisitNote(CustomModel):
    """Free-text visit note linked to a Canvas note."""

    note: Any = OneToOneField(
        NoteProxy,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="%(app_label)s__visit_note",
        primary_key=True,
    )
    content: Any = TextField(default="")
    updated_at: Any = DateTimeField(auto_now=True)
