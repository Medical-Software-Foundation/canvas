"""Structural tests for the plugin's custom data models.

Importing the module executes the class bodies (field definitions), and the
assertions below verify the model structure WITHOUT any database access.
"""

from django.db.models import (
    DateTimeField,
    ForeignKey,
    Index,
    JSONField,
    TextField,
)

from canvas_sdk.v1.data import ModelExtension, Note
from canvas_sdk.v1.data.base import CustomModel
from canvas_sdk.v1.data.document_reference import DocumentReference

from patient_visit_summary.models import (
    CustomizedNotePrint,
    DocumentReferenceProxy,
    NoteProxy,
    _generate_uuid,
)


# --- uuid default ---


class TestGenerateUuid:
    def test_returns_valid_uuid_string(self):
        from uuid import UUID

        value = _generate_uuid()
        assert isinstance(value, str)
        # Parses as a UUID and round-trips to the same canonical string.
        assert str(UUID(value)) == value

    def test_returns_unique_values(self):
        assert _generate_uuid() != _generate_uuid()

    def test_is_the_uuid_field_default(self):
        field = CustomizedNotePrint._meta.get_field("uuid")
        assert isinstance(field, TextField)
        assert field.default is _generate_uuid


# --- Proxy models ---


class TestProxyModels:
    def test_note_proxy_subclasses_bases(self):
        assert issubclass(NoteProxy, Note)
        assert issubclass(NoteProxy, ModelExtension)

    def test_document_reference_proxy_subclasses_bases(self):
        assert issubclass(DocumentReferenceProxy, DocumentReference)
        assert issubclass(DocumentReferenceProxy, ModelExtension)


# --- CustomizedNotePrint ---


class TestCustomizedNotePrintStatusConstants:
    def test_status_draft(self):
        assert CustomizedNotePrint.STATUS_DRAFT == "draft"

    def test_status_final(self):
        assert CustomizedNotePrint.STATUS_FINAL == "final"


class TestCustomizedNotePrintModel:
    def test_is_custom_model(self):
        assert issubclass(CustomizedNotePrint, CustomModel)

    def test_note_is_foreign_key_to_proxy(self):
        field = CustomizedNotePrint._meta.get_field("note")
        assert isinstance(field, ForeignKey)
        assert field.related_model is NoteProxy
        assert field.remote_field.field_name == "dbid"

    def test_document_reference_is_foreign_key_to_proxy(self):
        field = CustomizedNotePrint._meta.get_field("document_reference")
        assert isinstance(field, ForeignKey)
        assert field.related_model is DocumentReferenceProxy
        assert field.remote_field.field_name == "dbid"

    def test_text_fields_exist_with_empty_string_defaults(self):
        for name in (
            "header_text",
            "footer_text",
            "description",
            "html_content",
            "pdf_base64",
        ):
            field = CustomizedNotePrint._meta.get_field(name)
            assert isinstance(field, TextField), name
            assert field.default == "", name

    def test_status_field_defaults_to_draft(self):
        field = CustomizedNotePrint._meta.get_field("status")
        assert isinstance(field, TextField)
        assert field.default == CustomizedNotePrint.STATUS_DRAFT == "draft"

    def test_selection_is_json_field_defaulting_to_dict(self):
        field = CustomizedNotePrint._meta.get_field("selection")
        assert isinstance(field, JSONField)
        # default is the `dict` callable -> produces an empty dict
        assert field.default is dict
        assert field.default() == {}

    def test_datetime_fields_exist(self):
        for name in ("pdf_generated_at", "created_at", "updated_at"):
            field = CustomizedNotePrint._meta.get_field(name)
            assert isinstance(field, DateTimeField), name

    def test_created_at_is_auto_now_add(self):
        field = CustomizedNotePrint._meta.get_field("created_at")
        assert field.auto_now_add is True

    def test_updated_at_is_auto_now(self):
        field = CustomizedNotePrint._meta.get_field("updated_at")
        assert field.auto_now is True

    def test_meta_has_note_status_index(self):
        # The explicitly-declared composite index. Django may also auto-add
        # single-column indexes for the FK fields, so filter to ours.
        indexes = CustomizedNotePrint._meta.indexes
        composite = [i for i in indexes if i.fields == ["note", "status"]]
        assert len(composite) == 1
        assert isinstance(composite[0], Index)
