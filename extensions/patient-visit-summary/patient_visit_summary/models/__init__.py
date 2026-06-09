"""Custom data models for the Patient Visit Summary plugin."""

from uuid import uuid4

from canvas_sdk.v1.data import ModelExtension, Note
from canvas_sdk.v1.data.base import CustomModel
from canvas_sdk.v1.data.document_reference import DocumentReference
from django.db.models import (
    DO_NOTHING,
    DateTimeField,
    ForeignKey,
    Index,
    JSONField,
    TextField,
)


def _generate_uuid() -> str:
    """Default for the `uuid` column — a fresh random UUID string."""
    return str(uuid4())


class NoteProxy(Note, ModelExtension):
    pass


class DocumentReferenceProxy(DocumentReference, ModelExtension):
    pass


class CustomizedNotePrint(CustomModel):
    """The customize-print configuration for a note.

    `selection` JSON shape:
        {
            "checkedIds": ["cmd-1", "cmd-3", ...],  # atomic (leaf) ids
            "order":      ["cmd-1", "cmd-3", ...],  # flat DOM order of atomic ids
        }
    """

    STATUS_DRAFT = "draft"
    STATUS_FINAL = "final"

    # Non-enumerable external identifier. The internal `dbid` is a sequential
    # integer, so endpoints address rows by this random UUID to avoid IDOR.
    # Stored as text because the Canvas CustomModel sandbox does not allow
    # UUIDField; indexed via Meta below.
    uuid = TextField(default=_generate_uuid)
    note = ForeignKey(
        NoteProxy,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="customized_note_prints",
    )
    header_text = TextField(default="")
    footer_text = TextField(default="")
    selection = JSONField(default=dict)
    status = TextField(default=STATUS_DRAFT)
    description = TextField(default="")
    # Optional internal note saved on the DocumentReference (also stored
    # locally so the Previous Versions overlay can show it without a FHIR
    # round-trip). Never printed in the PDF body.
    comment = TextField(default="")
    html_content = TextField(default="")
    pdf_base64 = TextField(default="")
    document_reference = ForeignKey(
        DocumentReferenceProxy,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="customized_note_prints",
    )
    pdf_generated_at = DateTimeField()
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            Index(fields=["note", "status"]),
            Index(fields=["uuid"]),
        ]
