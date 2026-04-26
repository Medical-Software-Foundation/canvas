from canvas_sdk.v1.data.base import CustomModel
from django.db.models import (
    DO_NOTHING,
    BooleanField,
    DateTimeField,
    ForeignKey,
    UniqueConstraint,
)

from staff_directory.models.extensions import CustomStaff
from staff_directory.models.nucc import NuccTaxonomyCode


class StaffSpecialty(CustomModel):
    """Links a staff member to an NUCC taxonomy code."""

    staff = ForeignKey(
        CustomStaff,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="specialties",
    )
    nucc_code = ForeignKey(
        NuccTaxonomyCode,
        on_delete=DO_NOTHING,
        related_name="staff_specialties",
    )
    is_primary = BooleanField(default=False)

    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            UniqueConstraint(fields=["staff", "nucc_code"], name="unique_staff_specialty"),
        ]
