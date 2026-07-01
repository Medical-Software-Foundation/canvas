"""Filter-dropdown lookups.

Pure ORM readers with no dependency on the SimpleAPI instance.

Each lookup accepts an optional `cache`. These run on EVERY /table render (the
dashboard re-fetches the table on every sort/filter/pagination interaction) and
scan population-sized tables (ProtocolCurrent, Coverage, Staff). Filter options
change rarely, so the controller passes a cache to serve them for a short TTL.
When `cache` is None the lookup is always live (no behavior change) — that is
how the unit tests exercise the raw queries.
"""

from typing import Any

from django.db.models import Q

from canvas_sdk.v1.data.coverage import Coverage, CoverageStack
from canvas_sdk.v1.data.facility import Facility
from canvas_sdk.v1.data.protocol_current import ProtocolCurrent
from canvas_sdk.v1.data.protocol_result import ProtocolResultStatus
from canvas_sdk.v1.data.staff import Staff

# Filter dropdowns change rarely; a few minutes of staleness is acceptable and
# eliminates per-render scans of population-sized tables.
_DROPDOWN_TTL_SECONDS = 300

_FACILITIES_KEY = "panel_dropdown_facilities"
_PROTOCOL_TITLES_KEY = "panel_dropdown_protocol_titles"
_STAFF_KEY = "panel_dropdown_staff"
_INSURANCES_KEY = "panel_dropdown_insurances"


def get_facilities(cache: Any = None) -> list[dict]:
    """Get facilities for the filter dropdown."""
    if cache is not None:
        cached: list[dict] | None = cache.get(_FACILITIES_KEY)
        if cached is not None:
            return cached
    data = list(
        Facility.objects.all().values("id", "name").order_by("name")
    )
    if cache is not None:
        cache.set(_FACILITIES_KEY, data, timeout_seconds=_DROPDOWN_TTL_SECONDS)
    return data


def get_protocol_titles(cache: Any = None) -> list[str]:
    """Get distinct protocol titles with due gaps."""
    if cache is not None:
        cached: list[str] | None = cache.get(_PROTOCOL_TITLES_KEY)
        if cached is not None:
            return cached
    data = list(
        ProtocolCurrent.objects.filter(
            status=ProtocolResultStatus.STATUS_DUE,
        )
        .values_list("title", flat=True)
        .distinct()
        .order_by("title")
    )
    if cache is not None:
        cache.set(_PROTOCOL_TITLES_KEY, data, timeout_seconds=_DROPDOWN_TTL_SECONDS)
    return data


def get_staff(cache: Any = None) -> list[dict]:
    """Get staff members with clinical or hybrid roles for the care-team filter."""
    if cache is not None:
        cached: list[dict] | None = cache.get(_STAFF_KEY)
        if cached is not None:
            return cached
    staff_list = (
        Staff.objects.filter(Q(roles__domain="CLI") | Q(roles__domain="HYB"))
        .distinct()
        .values("id", "first_name", "last_name", "active")
        .order_by("last_name", "first_name")
    )
    data = [
        {
            "id": s["id"],
            "first_name": s["first_name"],
            "last_name": s["last_name"],
            "display_name": f"{s['first_name']} {s['last_name']}"
            + (" (inactive)" if not s["active"] else ""),
        }
        for s in staff_list
    ]
    if cache is not None:
        cache.set(_STAFF_KEY, data, timeout_seconds=_DROPDOWN_TTL_SECONDS)
    return data


def get_unique_insurances(cache: Any = None) -> list[str]:
    """Get unique insurance provider names for the filter dropdown."""
    if cache is not None:
        cached: list[str] | None = cache.get(_INSURANCES_KEY)
        if cached is not None:
            return cached
    data = list(
        Coverage.objects.filter(stack=CoverageStack.IN_USE)
        .exclude(issuer__name__isnull=True)
        .exclude(issuer__name="")
        .values_list("issuer__name", flat=True)
        .distinct()
        .order_by("issuer__name")
    )
    if cache is not None:
        cache.set(_INSURANCES_KEY, data, timeout_seconds=_DROPDOWN_TTL_SECONDS)
    return data
