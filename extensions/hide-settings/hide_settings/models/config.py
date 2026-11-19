from canvas_sdk.v1.data.base import CustomModel
from django.db.models import JSONField


class SettingsAccessConfig(CustomModel):
    """The role internal codes allowed to see the Settings menu item."""

    allowed_role_codes = JSONField(default=list)
