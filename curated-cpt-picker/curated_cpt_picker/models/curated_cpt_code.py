from django.db.models import (
    BooleanField,
    CharField,
    DateTimeField,
    IntegerField,
    JSONField,
)

from canvas_sdk.v1.data.base import CustomModel


class CuratedCptCode(CustomModel):
    """A CPT code that admins have added to the curated picker list.

    Each row is one selectable entry in the provider-facing modal. The
    same CPT code may appear multiple times with different modifier sets,
    distinguished by `description`.
    """

    cpt_code = CharField(max_length=16)
    description = CharField(max_length=255)
    # Non-negative constraint enforced at the API layer (admin_api validates input).
    # The plugin sandbox does not permit PositiveIntegerField.
    default_units = IntegerField(default=1)
    modifiers = JSONField(default=list, blank=True)
    display_order = IntegerField(default=0)
    enabled = BooleanField(default=True)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_order", "cpt_code"]
