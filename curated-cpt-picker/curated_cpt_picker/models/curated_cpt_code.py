from django.db import models

from canvas_sdk.v1.data.base import CustomModel


class CuratedCptCode(CustomModel):
    """A CPT code that admins have added to the curated picker list.

    Each row is one selectable entry in the provider-facing modal. The
    same CPT code may appear multiple times with different modifier sets,
    distinguished by `description`.
    """

    cpt_code = models.CharField(max_length=16)
    description = models.CharField(max_length=255)
    default_units = models.PositiveIntegerField(default=1)
    modifiers = models.JSONField(default=list, blank=True)
    display_order = models.PositiveIntegerField(default=0)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_order", "cpt_code"]
