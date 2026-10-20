from canvas_sdk.v1.data import ModelExtension, Staff
from canvas_sdk.v1.data.base import CustomModel
from django.db.models import (
    CASCADE,
    DO_NOTHING,
    BooleanField,
    DateTimeField,
    ForeignKey,
    Index,
    JSONField,
    OneToOneField,
    TextField,
    UniqueConstraint,
)


class CustomStaff(Staff, ModelExtension):
    """This plugin's handle on Staff, so reverse lookups stay private to the plugin."""


class Favorite(CustomModel):
    """A saved prescription or lab order that can be added to a note in one click.

    kind is "rx" or "lab". shared=True makes it a practice favorite: everyone can use it and only
    favorites admins change it. shared=False is a personal favorite: only its owner sees and
    changes it.

    details holds the order itself; its shape depends on kind and is checked by
    services.favorites.clean_details before every save:
      rx:  fdb_code, medication, sig, days_supply, quantity, unit, representative_ndc,
           ncpdp_quantity_qualifier_code, refills, pharmacy_ncpdp_id, pharmacy_name
      lab: lab_partner_id, lab_partner_name, tests [{code, name}], diagnoses [{code, text}],
           ordering_provider_id, ordering_provider_name, comment, fasting
    """

    kind = TextField()
    name = TextField()
    shared = BooleanField(default=False)
    owner = ForeignKey(CustomStaff, to_field="dbid", on_delete=DO_NOTHING, related_name="order_favorites")
    details = JSONField(default=dict)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        indexes = [Index(fields=["kind", "shared"])]


class HiddenFavorite(CustomModel):
    """A practice favorite one staff member took off their own list. Everyone else still sees it."""

    favorite = ForeignKey(Favorite, to_field="dbid", on_delete=CASCADE, related_name="hidden_by")
    staff = ForeignKey(CustomStaff, to_field="dbid", on_delete=DO_NOTHING, related_name="order_favorites_hidden")

    class Meta:
        constraints = [UniqueConstraint(fields=["favorite", "staff"], name="uq_order_favorite_hidden")]


class FavoritesAdmin(CustomModel):
    """A staff member who manages practice favorites and settings. The list lives in the plugin."""

    staff = OneToOneField(CustomStaff, to_field="dbid", on_delete=DO_NOTHING, related_name="order_favorites_admin")
    added_at = DateTimeField(auto_now_add=True)


class PracticeSetting(CustomModel):
    """A practice-wide setting, such as which order types are available."""

    key = TextField()
    value = JSONField(default=None, null=True)

    class Meta:
        constraints = [UniqueConstraint(fields=["key"], name="uq_order_favorites_setting")]
