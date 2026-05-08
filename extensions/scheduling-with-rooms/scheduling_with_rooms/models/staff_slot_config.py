"""Per-staff concurrent-slot capacity.

Replaces the legacy ``resource_limit`` plugin secret. Applies to both
schedulable providers and RR-role rooms; default ``1`` when no row is
configured for a given staff member.
"""

from canvas_sdk.v1.data.base import CustomModel
from django.db.models import CharField, IntegerField


class StaffSlotConfig(CustomModel):
    staff_key = CharField(max_length=64)
    concurrent_limit = IntegerField(default=1)


def get_concurrent_limit(staff_key: str, default: int = 1) -> int:
    """Return the configured concurrent limit for a staff member, or the default."""
    if not staff_key:
        return default
    val = (
        StaffSlotConfig.objects
        .filter(staff_key=staff_key)
        .values_list("concurrent_limit", flat=True)
        .first()
    )
    if val is None or val < 1:
        return default
    return int(val)


def replace_concurrent_limits(by_staff: dict[str, int]) -> None:
    """Replace-all save: for each staff_key in the dict, upsert the limit."""
    if not by_staff:
        return
    keys = list(by_staff.keys())
    StaffSlotConfig.objects.filter(staff_key__in=keys).delete()
    rows: list[StaffSlotConfig] = []
    for key, limit in by_staff.items():
        if not isinstance(key, str) or not key:
            continue
        try:
            li = int(limit)
        except (TypeError, ValueError):
            continue
        if li > 0:
            rows.append(StaffSlotConfig(staff_key=key, concurrent_limit=li))
    if rows:
        StaffSlotConfig.objects.bulk_create(rows)
