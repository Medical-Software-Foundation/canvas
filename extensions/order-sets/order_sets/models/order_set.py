# mypy: disable-error-code="var-annotated"

from canvas_sdk.v1.data.base import CustomModel
from django.db.models import (
    BooleanField,
    DateTimeField,
    Index,
    JSONField,
    TextField,
    UniqueConstraint,
)


class OrderSet(CustomModel):
    """A clinician-curated bundle of orders (lab, imaging, or POC).

    Stored as a CustomModel in the plugin's namespaced data tables so that
    sets persist across plugin upgrades and are queryable like any other
    Django model.
    """

    set_id = TextField()
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
        constraints = [
            UniqueConstraint(fields=["set_id"], name="uq_order_set_set_id"),
        ]
        indexes = [
            Index(fields=["is_shared"]),
            Index(fields=["created_by"]),
        ]
