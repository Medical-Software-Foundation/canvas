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


def get_concurrent_limit(staff_key: str, default: int = 1, cache: dict | None = None) -> int:
    """Return the configured concurrent limit for a staff member, or the default.

    Pass ``cache`` — ideally one built by :func:`prefetch_concurrent_limits` —
    when resolving limits repeatedly. The month view asks for the same handful
    of staff once per day, which is one query each without it.
    """
    if not staff_key:
        return default
    if cache is not None and staff_key in cache:
        return int(cache[staff_key])
    val = (
        StaffSlotConfig.objects
        .filter(staff_key=staff_key)
        .values_list("concurrent_limit", flat=True)
        .first()
    )
    limit = default if (val is None or val < 1) else int(val)
    if cache is not None:
        cache[staff_key] = limit
    return limit


def prefetch_concurrent_limits(staff_keys: list[str], default: int = 1) -> dict[str, int]:
    """Resolve limits for many staff in a single query.

    Returns an entry for *every* requested key — configured value or
    ``default`` — so the result can be handed straight to
    :func:`get_concurrent_limit` as an already-complete cache, with no
    fall-through queries for staff that have no row.
    """
    keys = [key for key in dict.fromkeys(staff_keys) if key]
    if not keys:
        return {}
    configured = dict(
        StaffSlotConfig.objects
        .filter(staff_key__in=keys)
        .values_list("staff_key", "concurrent_limit")
    )
    return {
        key: int(configured[key])
        if configured.get(key) is not None and configured[key] >= 1
        else default
        for key in keys
    }


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
