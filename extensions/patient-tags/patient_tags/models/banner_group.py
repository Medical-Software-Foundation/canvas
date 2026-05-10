from canvas_sdk.v1.data.base import CustomModel
from django.db.models import JSONField, TextField, UniqueConstraint


class BannerGroup(CustomModel):
    """A consolidated banner that one or more labels can attach to.

    Labels sharing the same BannerGroup render as a single banner whose narrative
    is the joined names of all assigned labels (separator configurable per group).
    Truncation to 90 characters is enforced when emitting the AddBannerAlert effect.
    """

    name = TextField()
    intent = TextField(default="info")
    placements = JSONField(default=list)
    separator = TextField(default=" • ")
    href = TextField(default="")

    class Meta:
        constraints = [
            UniqueConstraint(fields=["name"], name="unique_banner_group_name"),
        ]
