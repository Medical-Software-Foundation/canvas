from django.db.models import (
    DO_NOTHING,
    DateTimeField,
    ForeignKey,
    IntegerField,
    JSONField,
    TextField,
    UniqueConstraint,
)

from canvas_sdk.v1.data.base import CustomModel
from sticky_note.models.proxy import PatientProxy, StaffProxy


class StickyNote(CustomModel):
    """A sticky note attached to a patient chart.

    owner=NULL  -> shared note visible to all staff
    owner=staff -> user-specific note visible only to that staff member
    """

    patient = ForeignKey(
        PatientProxy,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="%(app_label)s__sticky_notes",
    )
    owner = ForeignKey(
        StaffProxy,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="%(app_label)s__sticky_notes",
        null=True,
    )
    content = TextField(default="", blank=True)
    updated_by = TextField(default="", blank=True)      # staff display name
    updated_by_id = TextField(default="", blank=True)   # staff UUID for reliable attribution
    updated_at = DateTimeField(auto_now=True)
    version = IntegerField(default=0)       # optimistic locking counter
    history = JSONField(default=list)       # DEPRECATED: kept for backward compat

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["patient", "owner"],
                name="uq_sticky_note_patient_owner",
            ),
        ]
