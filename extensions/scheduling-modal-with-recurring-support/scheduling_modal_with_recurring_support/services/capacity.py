from __future__ import annotations

from datetime import date, timedelta
from typing import NamedTuple

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.v1.data.appointment import Appointment
from canvas_sdk.v1.data.staff import Staff

from scheduling_modal_with_recurring_support.services.availability import _count_free_slots

WINDOW_DAYS = 7
DEFAULT_APPOINTMENT_LENGTH = 30
CACHE_TTL_SECONDS = 300


class CapacityMetric(NamedTuple):
    pct_filled: float
    filled_count: int
    free_count: int
    total_count: int
    has_capacity: bool


def appointment_counts_last_30_days_bulk(
    staff_list: list[Staff],
    today: date | None = None,
) -> dict[str, int]:
    """Appointment counts per provider over the past 30 days.

    A single grouped query keyed by staff id rather than one count per
    provider. Returns a dict keyed by the stringified staff id with a default
    of zero for providers that have no appointments in the window.
    """
    if not staff_list:
        return {}

    from django.db.models import Count

    today = today or date.today()
    thirty_days_ago = today - timedelta(days=30)
    rows = (
        Appointment.objects.filter(
            provider__in=staff_list,
            start_time__date__gte=thirty_days_ago,
            start_time__date__lt=today,
        )
        .values("provider")
        .annotate(count=Count("id"))
    )
    counts = {str(row["provider"]): row["count"] for row in rows}
    return {str(staff.id): counts.get(str(staff.id), 0) for staff in staff_list}


def upcoming_appointment_counts_7_days_bulk(
    staff_list: list[Staff],
    today: date | None = None,
) -> dict[str, int]:
    """Appointment counts per provider over the next seven days.

    One grouped query keyed by staff id for the next seven days window.
    Returns a dict keyed by the stringified staff id with a default of zero
    for providers that have no appointments in the window.
    """
    if not staff_list:
        return {}

    from django.db.models import Count

    today = today or date.today()
    seven_days = today + timedelta(days=7)
    rows = (
        Appointment.objects.filter(
            provider__in=staff_list,
            start_time__date__gte=today,
            start_time__date__lte=seven_days,
        )
        .values("provider")
        .annotate(count=Count("id"))
    )
    counts = {str(row["provider"]): row["count"] for row in rows}
    return {str(staff.id): counts.get(str(staff.id), 0) for staff in staff_list}


def filled_counts_next_window_bulk(
    staff_list: list[Staff],
    today: date | None = None,
) -> dict[str, int]:
    """Bulk filled-appointment counts for the next WINDOW_DAYS days.

    Mirrors the other bulk count helpers. One grouped query keyed by staff id
    over the next WINDOW_DAYS days, excluding cancelled appointments, matching
    the filled filter inside filled_pct_next_window. Returns a dict keyed by the
    stringified staff id with a default of zero for providers that have no
    appointments in the window. Lets the ranking loop avoid one count query per
    provider.
    """
    if not staff_list:
        return {}

    from django.db.models import Count

    today = today or date.today()
    window_end = today + timedelta(days=WINDOW_DAYS)
    rows = (
        Appointment.objects.filter(
            provider__in=staff_list,
            start_time__date__gte=today,
            start_time__date__lt=window_end,
        )
        .exclude(status="cancelled")
        .values("provider")
        .annotate(count=Count("id"))
    )
    counts = {str(row["provider"]): row["count"] for row in rows}
    return {str(staff.id): counts.get(str(staff.id), 0) for staff in staff_list}


def filled_pct_next_window(
    staff: Staff,
    fhir_base_url: str,
    access_token: str,
    location_id: str,
    appointment_length: int = DEFAULT_APPOINTMENT_LENGTH,
    today: date | None = None,
    filled_override: int | None = None,
) -> CapacityMetric:
    """Percentage of bookable slots already filled for the next WINDOW_DAYS days.

    filled is Appointments in window with status not cancelled, the simplified
    outstanding filter. free is the FHIR Slot search
    count via Fumage over the same window. pct equals filled divided by total
    times 100, or 0.0 when total is zero.

    filled_override lets a bulk caller pass a pre-counted filled value so the
    ranking loop skips the per-provider count query. When None the count is
    queried here as before. It is ignored on a cache hit, since the cached
    metric already carries its own filled count.
    """
    today = today or date.today()
    window_end = today + timedelta(days=WINDOW_DAYS)
    cache_key = f"cnv898:filled_pct:{staff.id}:{today.isoformat()}:{appointment_length}"

    cache = get_cache()
    cached = cache.get(cache_key)
    if cached is not None:
        return CapacityMetric(*cached)

    if filled_override is not None:
        filled = filled_override
    else:
        filled = (
            Appointment.objects.filter(
                provider=staff,
                start_time__date__gte=today,
                start_time__date__lt=window_end,
            )
            .exclude(status="cancelled")
            .count()
        )

    free = _count_free_slots(
        fhir_base_url=fhir_base_url,
        access_token=access_token,
        provider_id=str(staff.id),
        location_id=location_id,
        start_date=today,
        end_date=window_end,
        duration_minutes=appointment_length,
    )

    total = filled + free
    pct = (filled / total * 100) if total > 0 else 0.0

    metric = CapacityMetric(
        pct_filled=round(pct, 1),
        filled_count=filled,
        free_count=free,
        total_count=total,
        has_capacity=total > 0,
    )
    cache.set(cache_key, tuple(metric), CACHE_TTL_SECONDS)
    return metric


def bust_filled_pct(
    staff_id: str,
    appointment_length: int = DEFAULT_APPOINTMENT_LENGTH,
    today: date | None = None,
) -> None:
    """Invalidate today's filled_pct cache entry for a single provider.

    Fire and forget. cache.delete returns silently when the key is absent.
    """
    today = today or date.today()
    cache_key = f"cnv898:filled_pct:{staff_id}:{today.isoformat()}:{appointment_length}"
    get_cache().delete(cache_key)
