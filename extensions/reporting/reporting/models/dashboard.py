"""Persisted dashboards: an ordered grid of saved-report widgets."""

from django.db.models import (
    DO_NOTHING,
    DateTimeField,
    ForeignKey,
    IntegerField,
    JSONField,
    TextField,
)

from canvas_sdk.v1.data.base import CustomModel
from reporting.models.proxy import StaffProxy


class Dashboard(CustomModel):
    """A named, owned, optionally-shared grid of report widgets.

    layout: {"widgets": [{"report_id": int, "span": 1-4, "viz": str|None}, ...]}
            (list order = grid order)
    default_period: {granularity, count, include_rolling_12} | {} -> widgets inherit
            this period; when empty each widget uses its report's own period.
    """

    owner = ForeignKey(
        StaffProxy,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="%(app_label)s__dashboards",
        null=True,
    )
    name = TextField(default="", blank=True)
    visibility = TextField(default="private")  # "private" | "shared"
    layout = JSONField(default=dict)
    default_period = JSONField(default=dict)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)
    version = IntegerField(default=0)
