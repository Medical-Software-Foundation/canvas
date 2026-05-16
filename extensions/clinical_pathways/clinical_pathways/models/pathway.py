from canvas_sdk.v1.data.base import CustomModel
from django.db.models import (
    BooleanField,
    DateTimeField,
    Index,
    TextField,
)


class Pathway(CustomModel):
    """A named clinical pathway (top-level container)."""

    title = TextField()
    description = TextField(default="")
    recommendation = TextField(default="")
    is_active = BooleanField(default=True)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            Index(fields=["title"]),
            Index(fields=["is_active"]),
        ]
