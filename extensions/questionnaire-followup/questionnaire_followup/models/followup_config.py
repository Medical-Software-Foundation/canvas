"""Custom-data store for the admin-configured questionnaire pairing rules.

A single row (`key="active"`) holds the whole rules document as a JSON string in
`payload`. The admin page edits it through form controls; JSON is the storage
format only, never shown to or edited by a user.

A single JSON document rather than one row per rule: the rule set is small, is
always read and written whole, and its shape is still moving. Structured columns
would buy querying we never do at the cost of a migration per field.

NOTE: CustomModels MUST live in a ``models/`` package (not a single models.py),
or the SDK never generates the migration and the table is not created.
"""

from canvas_sdk.v1.data.base import CustomModel
from django.db.models import CharField, TextField, UniqueConstraint


class FollowUpConfig(CustomModel):
    """Single-row JSON config document for the questionnaire pairing rules."""

    key: CharField = CharField(max_length=64)
    payload: TextField = TextField(default="")

    class Meta:
        constraints = [UniqueConstraint(fields=["key"], name="uq_questionnaire_followup_key")]
