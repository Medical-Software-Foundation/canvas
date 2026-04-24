from django.db.models import DateTimeField, Index, IntegerField, TextField

from canvas_sdk.v1.data.base import CustomModel

NOTE_TYPE_CHOICES = [("shared", "shared"), ("user", "user")]
ACTION_CHOICES = [("created", "created"), ("edited", "edited"), ("cleared", "cleared")]


class StickyNoteAudit(CustomModel):
    """Append-only audit log for sticky note changes.

    Each row is an immutable record of a note state before it was modified.
    No ForeignKeys — intentionally denormalized so audit survives note deletion.
    """

    patient_dbid = IntegerField()
    patient_uuid = TextField()
    note_type = TextField(choices=NOTE_TYPE_CHOICES)
    owner_dbid = IntegerField(null=True)
    action = TextField(choices=ACTION_CHOICES)
    content = TextField(default="", blank=True)
    edited_by_id = TextField()
    edited_by_name = TextField()
    edited_at = DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            Index(
                fields=["patient_dbid", "note_type", "-edited_at"],
                name="idx_audit_patient_type_at",
            ),
            Index(
                fields=["patient_dbid", "note_type", "owner_dbid", "-edited_at"],
                name="idx_audit_patient_owner_at",
            ),
        ]
