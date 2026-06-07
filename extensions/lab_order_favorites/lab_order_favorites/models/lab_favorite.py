"""CustomModel for storing user-created lab order favorites."""

# mypy: disable-error-code="var-annotated"

from canvas_sdk.v1.data import ModelExtension, Staff
from canvas_sdk.v1.data.base import CustomModel
from django.db.models import (
    CASCADE,
    BooleanField,
    DateTimeField,
    ForeignKey,
    Index,
    JSONField,
    TextField,
    UniqueConstraint,
)


class CustomStaff(Staff, ModelExtension):
    """Proxy model to allow ForeignKey references to Staff from CustomModel."""

    pass


class LabFavorite(CustomModel):
    """A user-created lab order favorite.

    Each favorite is bound to exactly one LabPartner; all of its tests must
    belong to that partner so it inserts as a single staged LabOrder command.
    There are no default/seeded favorites - the library starts empty and is
    populated by manual add or CSV bulk upload.
    """

    custom_id = TextField()
    name = TextField()
    lab_partner_id = TextField()
    lab_partner_name = TextField(default="")
    # tests: list of {"order_code": str, "order_name": str, "cpt_code": str}
    tests = JSONField(default=list)
    tags = JSONField(default=list)
    fasting_required = BooleanField(default=False)
    comment = TextField(default="")
    diagnosis_codes = JSONField(default=list)
    # Default ordering provider (Staff id). Empty = fall back to the inserting user.
    ordering_provider_key = TextField(default="")
    ordering_provider_name = TextField(default="")
    is_shared = BooleanField(default=True)
    created_by = ForeignKey(
        CustomStaff,
        to_field="dbid",
        on_delete=CASCADE,
        related_name="created_lab_favorites",
    )
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            UniqueConstraint(fields=["custom_id"], name="uq_lab_favorite_custom_id"),
        ]
        indexes = [
            Index(fields=["is_shared"]),
            Index(fields=["lab_partner_id"]),
        ]
