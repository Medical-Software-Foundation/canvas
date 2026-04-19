"""CustomModel for storing user-created prescription favorites."""

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
    """Proxy model to allow ForeignKey references to Staff from CustomModel."""

    pass


class CustomFavorite(CustomModel):
    """A user-created prescription favorite stored in the plugin's custom data namespace.

    Hardcoded/default favorites are NOT stored here - they live in medications.py.
    Only user-added custom favorites use this model.
    """

    custom_id = TextField()
    display_name = TextField()
    label = TextField(default="")
    label_color = TextField(default="")
    medication_name = TextField(default="")
    fdb_code = TextField()
    sig = TextField()
    days_supply = IntegerField()
    quantity_to_dispense = DecimalField(max_digits=10, decimal_places=2)
    unit = TextField()
    refills = IntegerField(default=0)
    representative_ndc = TextField()
    ncpdp_quantity_qualifier_code = TextField()
    generic_substitution_allowed = BooleanField(default=True)
    search_terms = JSONField(default=list)
    default_pharmacy_ncpdp_id = TextField(default="")
    default_pharmacy_name = TextField(default="")
    is_shared = BooleanField(default=True)
    created_by = ForeignKey(
        CustomStaff,
        to_field="dbid",
        on_delete=CASCADE,
        related_name="created_favorites",
    )
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            UniqueConstraint(fields=["custom_id"], name="uq_custom_favorite_custom_id"),
        ]
        indexes = [
            Index(fields=["is_shared"]),
        ]


class HiddenDefault(CustomModel):
    """Tracks which default favorites a staff member has hidden.

    Each record means staff member hidden_by_id has hidden the default
    favorite with ID default_id (e.g., "wegovy_0.25mg").
    """

    default_id = TextField()
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
