from canvas_sdk.v1.data.base import CustomModel
from django.db.models import DO_NOTHING, DateTimeField, ForeignKey, Index, IntegerField, TextField

from staff_directory.models.extensions import CustomStaff


class ClinicalTraining(CustomModel):
    """A residency, fellowship, internship, or other post-graduate training program."""

    staff = ForeignKey(
        CustomStaff,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="trainings",
    )
    institution = TextField()
    program_type = TextField()
    specialty_area = TextField(default="")
    start_year = IntegerField(default=0)
    end_year = IntegerField(default=0)
    notes = TextField(default="")

    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        indexes = [Index(fields=["staff", "-end_year"])]
