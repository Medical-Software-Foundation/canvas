from canvas_sdk.v1.data.base import CustomModel
from django.db.models import (
    DO_NOTHING,
    BooleanField,
    ForeignKey,
    TextField,
    UniqueConstraint,
)

from patient_tags.models.banner_group import BannerGroup


class Label(CustomModel):
    """A user-defined patient label.

    `assignable_in_chart` / `assignable_in_profile` gate where a clinician can
    add or remove this label from a patient. Once assigned, a label is visible
    in both contexts regardless — the assigned section of the pill grid lists
    every assignment, and the per-context flag only filters the "available"
    pool and disables pill-toggle in the wrong context.
    """

    name = TextField()
    description = TextField(default="")
    color = TextField(default="blue")
    # db_column preserves existing data; the legacy field names conflated
    # visibility and assignability — the rename clarifies intent.
    assignable_in_chart = BooleanField(default=True, db_column="show_in_chart")
    assignable_in_profile = BooleanField(default=True, db_column="show_in_profile")
    banner_group = ForeignKey(
        BannerGroup,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="labels",
    )

    class Meta:
        constraints = [
            UniqueConstraint(fields=["name"], name="unique_label_name"),
        ]
