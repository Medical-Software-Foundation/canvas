"""Singleton row holding the plugin's campaign configuration.

The dataclass schema lives in `services/config.py` and is (de)serialized to
the `data` JSONField. Only one row is ever used — `load_config` /
`save_config` in the service layer enforce this at the application level.
"""

from canvas_sdk.v1.data.base import CustomModel
from django.db.models import JSONField


class CampaignConfigRecord(CustomModel):
    data = JSONField(default=dict)
