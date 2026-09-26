"""Custom Data models for clinical-favorites.

ClinicalFavorite unifies medication and condition favorites in one table.
HiddenDefault tracks per-staff visibility overrides for seeded defaults.
CustomStaff is a proxy that lets Custom Data ForeignKeys reach Staff.
"""

# mypy: disable-error-code="var-annotated"

from canvas_sdk.v1.data import ModelExtension, Staff
from canvas_sdk.v1.data.base import CustomModel
from django.db.models import (
    CASCADE,
    BooleanField,
    DateTimeField,
    DecimalField,
    ForeignKey,
    Index,
    IntegerField,
    JSONField,
    TextField,
    UniqueConstraint,
)


class CustomStaff(Staff, ModelExtension):
    """Proxy so Custom Data ForeignKey references can reach Staff."""

    pass


class ClinicalFavorite(CustomModel):
    """Unified favorite record for medications and conditions."""

    custom_id = TextField()
    favorite_type = TextField()
    code = TextField()
    display_name = TextField()
    label = TextField(default="")
    label_color = TextField(default="")
    group_name = TextField(default="")
    is_shared = BooleanField(default=True)

    created_by = ForeignKey(
        CustomStaff,
        to_field="dbid",
        on_delete=CASCADE,
        null=True,
        related_name="created_clinical_favorites",
    )
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    medication_name = TextField(default="")
    fdb_code = TextField(default="")
    sig = TextField(default="")
    days_supply = IntegerField(null=True)
    quantity_to_dispense = DecimalField(
        max_digits=10, decimal_places=2, null=True,
    )
    unit = TextField(default="")
    refills = IntegerField(default=0)
    representative_ndc = TextField(default="")
    ncpdp_quantity_qualifier_code = TextField(default="")
    generic_substitution_allowed = BooleanField(default=True)
    search_terms = JSONField(default=list)
    default_pharmacy_ncpdp_id = TextField(default="")
    default_pharmacy_name = TextField(default="")
    note_to_pharmacist = TextField(default="")

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["custom_id"],
                name="uq_clinical_favorite_custom_id",
            ),
            UniqueConstraint(
                fields=["created_by", "favorite_type", "code"],
                name="uq_clinical_favorite_owner_type_code",
            ),
        ]
        indexes = [
            Index(fields=["is_shared"]),
            Index(fields=["favorite_type"]),
            Index(fields=["favorite_type", "is_shared"]),
        ]


class HiddenDefault(CustomModel):
    """Tracks which seeded defaults a staff member has hidden."""

    default_id = TextField()
    favorite_type = TextField(default="medication")
    hidden_by = ForeignKey(
        CustomStaff,
        to_field="dbid",
        on_delete=CASCADE,
        related_name="hidden_defaults",
    )

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["default_id", "hidden_by_id"],
                name="uq_hidden_default_per_staff",
            ),
        ]
