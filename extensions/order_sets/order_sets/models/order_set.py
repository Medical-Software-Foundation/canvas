"""Persistent storage for order-set definitions.

An earlier draft of this plugin kept the dicts in the plugin cache with a
14-day TTL — meaning a set nobody touched for two weeks would silently
vanish. Order-set definitions are reference data (curated practice-wide,
or maintained as a provider's personal favorites), so they belong in a
durable custom table, not a cache.
"""
from canvas_sdk.v1.data.base import CustomModel
from django.db.models import BooleanField, DateTimeField, Index, JSONField, TextField


class OrderSet(CustomModel):
    set_id = TextField()  # public UUID; what shows up in URLs and JSON
    name = TextField()
    description = TextField(default="")
    order_type = TextField(default="lab")
    is_shared = BooleanField(default=False)
    created_by = TextField(default="")
    created_by_name = TextField(default="")
    diagnosis_codes = JSONField(default=list)
    lab_partner = TextField(default="")
    lab_partner_name = TextField(default="")
    items = JSONField(default=list)
    fasting_required = BooleanField(default=False)
    comment = TextField(default="")
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            Index(fields=["set_id"]),
            Index(fields=["is_shared", "created_by"]),
        ]
