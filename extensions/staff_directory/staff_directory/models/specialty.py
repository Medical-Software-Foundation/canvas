from canvas_sdk.v1.data.base import CustomModel
from django.db.models import (
    DO_NOTHING,
    BooleanField,
    DateTimeField,
    ForeignKey,
    Index,
    TextField,
    UniqueConstraint,
)

from staff_directory.models.extensions import CustomStaff


class NuccTaxonomyCode(CustomModel):
    """A row from the NUCC Healthcare Provider Taxonomy Code Set."""

    code = TextField()
    grouping = TextField()
    classification = TextField()
    specialization = TextField(default="")
    definition = TextField(default="")
    display_name = TextField()

    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            UniqueConstraint(fields=["code"], name="unique_nucc_code"),
        ]
        indexes = [
            Index(fields=["classification"]),
            Index(fields=["specialization"]),
            Index(fields=["display_name"]),
        ]


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
        to_field="dbid",
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
