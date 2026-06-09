"""Persisted saved-report definitions (Canvas-provisioned custom data table)."""

from canvas_sdk.v1.data.base import CustomModel
from reporting.models.proxy import StaffProxy


class Report(CustomModel):
    """A saved report: a named, owned, optionally-shared query definition.

    visibility: "private" (owner only) or "shared" (whole org).
    definition: the JSON report spec consumed by the /run endpoint
        (dataset_key, measure_key, group_by, filters, period).
    """

    from django.db.models import (
        DO_NOTHING,
        DateTimeField,
        ForeignKey,
        IntegerField,
        JSONField,
        TextField,
    )

    owner = ForeignKey(
        StaffProxy,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="%(app_label)s__reports",
        null=True,
    )
    name = TextField(default="", blank=True)
    category = TextField(default="", blank=True)
    visibility = TextField(default="private")  # "private" | "shared"
    definition = JSONField(default=dict)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)
    version = IntegerField(default=0)  # optimistic-lock counter
