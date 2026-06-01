from typing import Any

from django.db.models import DO_NOTHING, DateTimeField, OneToOneField, TextField

from canvas_sdk.v1.data.base import CustomModel
from soap_note.models.proxy import NoteProxy


class SoapNoteData(CustomModel):
    """Structured SOAP note data linked to a Canvas note."""

    note: Any = OneToOneField(
        NoteProxy,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="%(app_label)s__soap_note",
        primary_key=True,
    )
    subjective: Any = TextField(default="")
    objective: Any = TextField(default="")
    assessment: Any = TextField(default="")
    plan: Any = TextField(default="")
    updated_at: Any = DateTimeField(auto_now=True)
