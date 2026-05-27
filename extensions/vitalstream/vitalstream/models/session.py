from django.db.models import (
    DO_NOTHING,
    DateTimeField,
    Index,
    IntegerField,
    OneToOneField,
    TextField,
    UniqueConstraint,
)

from canvas_sdk.v1.data.base import CustomModel

from vitalstream.models.proxy import NoteProxy


class SessionStatus:
    OPEN = "open"
    CLOSED = "closed"


class VitalstreamSession(CustomModel):
    """A VitalStream device session bound to a single Canvas note.

    At most one row per note exists. `note` is a OneToOneField so uniqueness
    is handled at the column level. The row is created when the staff member
    first opens the VitalStream UI on a note and stays as the device's
    pairing target for the life of the note. When the user clicks End
    Session & Save Summary, `status` flips to "closed"; further device
    readings posted against the session are then rejected.
    """

    note = OneToOneField(
        NoteProxy,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="%(app_label)s__vitalstream_session",
    )
    session_id = TextField()
    staff_id = TextField()
    status = TextField(default=SessionStatus.OPEN)
    started_at = DateTimeField(auto_now_add=True)
    ended_at = DateTimeField(null=True, blank=True)
    summary_increment_minutes = IntegerField(null=True, blank=True)

    class Meta:
        constraints = [
            UniqueConstraint(fields=["session_id"], name="uq_vitalstream_session_id"),
        ]
        indexes = [
            Index(fields=["session_id"]),
            Index(fields=["status"]),
        ]
