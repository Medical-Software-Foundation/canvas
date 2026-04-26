from canvas_sdk.v1.data.base import CustomModel
from django.db.models import (
    DO_NOTHING,
    DateField,
    DateTimeField,
    ForeignKey,
    Index,
    TextField,
)

from staff_directory.models.extensions import CustomStaff


class BoardCertification(CustomModel):
    """A board certification held by a staff member."""

    staff = ForeignKey(
        CustomStaff,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="certifications",
    )
    board_name = TextField()
    specialty = TextField()
    certification_number = TextField(default="")
    issued_date = DateField(null=True)
    expiration_date = DateField(null=True)
    notes = TextField(default="")

    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            Index(fields=["expiration_date"]),
        ]
