from canvas_sdk.v1.data.base import CustomModel
from django.db.models import DO_NOTHING, DateTimeField, ForeignKey, Index, IntegerField, TextField

from staff_directory.models.extensions import CustomStaff


class Education(CustomModel):
    """A single degree or educational credential held by a staff member."""

    staff = ForeignKey(
        CustomStaff,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="educations",
    )
    institution = TextField()
    degree = TextField()
    field_of_study = TextField(default="")
    graduation_year = IntegerField(default=0)
    notes = TextField(default="")

    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        indexes = [Index(fields=["staff", "-graduation_year"])]
