"""Custom-data store for the admin-configured group therapy templates.

A single row (`key="active"`) holds the whole templates config as a JSON string
in `payload`. The admin page edits it through form controls; JSON is the storage
format only, never shown to a user.

NOTE: CustomModels MUST live in a ``models/`` package (not a single models.py),
or the SDK never generates the migration and the table is not created.
"""

from canvas_sdk.v1.data.base import CustomModel
from django.db.models import CharField, TextField, UniqueConstraint


class GroupTherapyConfig(CustomModel):
    """Single-row JSON config document for the group therapy templates."""

    key = CharField(max_length=64)
    payload = TextField(default="")

    class Meta:
        constraints = [UniqueConstraint(fields=["key"], name="uq_group_therapy_config_key")]
