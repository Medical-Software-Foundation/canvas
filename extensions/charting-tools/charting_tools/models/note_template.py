"""Persistent storage for note template definitions."""

from django.db.models import BooleanField, DateTimeField, Index, JSONField, TextField

from canvas_sdk.v1.data.base import CustomModel


class NoteTemplate(CustomModel):
    """A note template, quickpick, or order set (``kind``), all built the same way.

    ``kind`` is "template", "quickpick", or "order_set"; NULL on rows saved
    before the field existed, which are templates.

    ``commands`` is an ordered list of dicts, one per command to originate:
    ``{"schema_key": str, "carry_forward": bool, "scribe_prompt": str,
    "fields": {...}}``, where ``fields`` holds the values the admin pre-filled
    on the command's form (see ``command_forms.py``).

    ``diagnosis_sources`` are the ICD-10-CM picks a quickpick or order set is
    for: ``{"code", "display", "include_children"}``. ``diagnosis_match_codes``
    is every code they cover, dot-stripped, expanded through UMLS at save time
    so the in-command panel compares against it without calling UMLS.

    ``note_types`` lists the note types whose new notes get this template
    automatically: ``{"unique_identifier": str, "name": str}``, keyed by the
    identifier every version of a note type shares.

    Columns added after the first release are NULL on older rows, so readers
    treat ``show_in_menu`` NULL as True and ``note_types`` NULL as empty.
    """

    template_id = TextField()  # public UUID used in button keys and URLs
    name = TextField()
    commands = JSONField(default=list)
    active = BooleanField(default=True)
    show_in_menu = BooleanField(default=True)
    note_types = JSONField(default=list)
    kind = TextField(default="template")
    show_in_panel = BooleanField(default=False)
    diagnosis_sources = JSONField(default=list)
    diagnosis_match_codes = JSONField(default=list)
    # Quickpicks and order sets: admin-defined labels clinicians filter by in the panel.
    tags = JSONField(default=list)
    # Kind "rule" only: conditions and action, see rules.py.
    rule = JSONField(default=dict)
    created_by = TextField(default="")
    updated_by = TextField(default="")
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            Index(fields=["template_id"]),
            Index(fields=["active", "name"]),
        ]
