"""Each staff member's saved dashboard settings."""

from canvas_sdk.v1.data.base import CustomModel
from django.db.models import DO_NOTHING, JSONField, OneToOneField

from failed_fax_dashboard.models.proxies import StaffProxy


class DashboardPreference(CustomModel):
    """Search, filters, sort, and collapsed sections per tab, for one staff member."""

    staff: OneToOneField = OneToOneField(
        StaffProxy,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="dashboard_preference",
    )
    settings: JSONField = JSONField(default=dict)
