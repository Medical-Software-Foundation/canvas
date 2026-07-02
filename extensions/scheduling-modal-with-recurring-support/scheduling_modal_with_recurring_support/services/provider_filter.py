from __future__ import annotations

from datetime import date, datetime
from typing import NamedTuple

from canvas_sdk.v1.data.staff import Staff

from scheduling_modal_with_recurring_support.services.availability import (
    DEFAULT_DURATION_MINUTES,
    SeriesScore,
    best_series_availability,
    series_scores_by_first_date,
)
from scheduling_modal_with_recurring_support.services.capacity import (
    CapacityMetric,
    appointment_counts_last_30_days_bulk,
    filled_counts_next_window_bulk,
    filled_pct_next_window,
    upcoming_appointment_counts_7_days_bulk,
)
from scheduling_modal_with_recurring_support.services.recurrence import (
    RecurrenceRule,
    iter_candidate_first_dates,
)

RECOMMENDED_TOP_N = 3


class ProviderSummary(NamedTuple):
    id: str
    full_name: str
    npi_number: str
    pct_filled: float
    filled_count: int
    free_count: int
    total_count: int
    has_capacity: bool
    appointments_last_30_days: int
    upcoming_7_days: int
    tier: str  # recommended or other


def licensed_providers_for_state(
    patient_state: str,
    fhir_base_url: str,
    access_token: str,
    location_id: str,
) -> list[ProviderSummary]:
    """Return active providers licensed in patient_state, sorted by pct_filled ascending.

    When patient_state is empty, the license filter is skipped and every active
    provider is returned. This supports the scheduling fallback when the patient
    has no state on file.

    Zero capacity providers sort to the bottom via the tuple key.
    """
    today = date.today()
    active_staff = Staff.objects.filter(active=True).prefetch_related("licenses")

    if patient_state:
        matching: list[Staff] = [
            staff
            for staff in active_staff
            if _has_valid_license(staff, patient_state, today)
        ]
    else:
        matching = list(active_staff)

    counts_30 = appointment_counts_last_30_days_bulk(matching, today=today)
    counts_7 = upcoming_appointment_counts_7_days_bulk(matching, today=today)
    filled_counts = filled_counts_next_window_bulk(matching, today=today)

    raw: list[tuple[Staff, CapacityMetric, int, int]] = [
        (
            staff,
            filled_pct_next_window(
                staff,
                fhir_base_url=fhir_base_url,
                access_token=access_token,
                location_id=location_id,
                filled_override=filled_counts.get(str(staff.id), 0),
            ),
            counts_30.get(str(staff.id), 0),
            counts_7.get(str(staff.id), 0),
        )
        for staff in matching
    ]

    raw.sort(key=lambda r: (not r[1].has_capacity, r[1].pct_filled))

    tiers = _assign_tiers([r[1] for r in raw])

    return [
        ProviderSummary(
            id=str(staff.id),
            full_name=staff.full_name,
            npi_number=staff.npi_number or "",
            pct_filled=metric.pct_filled,
            filled_count=metric.filled_count,
            free_count=metric.free_count,
            total_count=metric.total_count,
            has_capacity=metric.has_capacity,
            appointments_last_30_days=count_30,
            upcoming_7_days=count_7,
            tier=tiers[i],
        )
        for i, (staff, metric, count_30, count_7) in enumerate(raw)
    ]


def _assign_tiers(metrics: list[CapacityMetric]) -> list[str]:
    """Mark the top N most available providers as recommended.

    The metrics arrive already sorted by rank, capacity holders first and most
    available first, so the recommended set is the first N entries that have
    capacity. A provider with no capacity never earns the badge even when it
    lands within the first N of a thin list.
    """
    return [
        "recommended" if i < RECOMMENDED_TOP_N and m.has_capacity else "other"
        for i, m in enumerate(metrics)
    ]


def _has_valid_license(staff: Staff, state: str, today: date) -> bool:
    for lic in staff.licenses.all():
        if lic.state != state:
            continue
        if lic.expiration_date is None or lic.expiration_date >= today:
            return True
    return False


class ProviderSeriesSummary(NamedTuple):
    id: str
    full_name: str
    npi_number: str
    series_available_count: int
    series_total_count: int
    best_hhmm: str
    has_capacity: bool
    tier: str  # recommended or other


def providers_ranked_by_series_availability(
    patient_state: str,
    rule: RecurrenceRule,
    start_date: date,
    fhir_base_url: str,
    access_token: str,
    tz_offset_minutes: int = 0,
    duration_minutes: int = DEFAULT_DURATION_MINUTES,
    now: datetime | None = None,
) -> list[ProviderSeriesSummary]:
    """Rank licensed providers by the series they can actually take.

    Unlike licensed_providers_for_state, which ranks on a seven day load proxy
    before the dates exist, this scores every provider against the real
    projected occurrence dates at the real duration. The score is the best
    achievable series, the count of occurrences free at the best shared start
    time. Providers are sorted most coverable first, then by name for a stable
    order, so a provider whose start date has no slot scores zero and sinks to
    the bottom. The recommended badge marks the top three with the capacity
    guard, on this honest number rather than on load.

    The license filter mirrors licensed_providers_for_state. An empty
    patient_state skips it and scores every active provider.
    """
    today = date.today()
    active_staff = Staff.objects.filter(active=True).prefetch_related("licenses")

    if patient_state:
        matching: list[Staff] = [
            staff
            for staff in active_staff
            if _has_valid_license(staff, patient_state, today)
        ]
    else:
        matching = list(active_staff)

    scored: list[tuple[Staff, SeriesScore]] = [
        (
            staff,
            best_series_availability(
                fhir_base_url=fhir_base_url,
                access_token=access_token,
                provider_id=str(staff.id),
                rule=rule,
                start_date=start_date,
                tz_offset_minutes=tz_offset_minutes,
                duration_minutes=duration_minutes,
                now=now,
            ),
        )
        for staff in matching
    ]

    scored.sort(key=lambda r: (-r[1].available_count, r[0].full_name))

    tiers = _assign_series_tiers([score for _, score in scored])

    return [
        ProviderSeriesSummary(
            id=str(staff.id),
            full_name=staff.full_name,
            npi_number=staff.npi_number or "",
            series_available_count=score.available_count,
            series_total_count=score.total_count,
            best_hhmm=score.best_hhmm,
            has_capacity=score.available_count > 0,
            tier=tiers[i],
        )
        for i, (staff, score) in enumerate(scored)
    ]


def _assign_series_tiers(scores: list[SeriesScore]) -> list[str]:
    """Mark the top N providers with real series coverage as recommended.

    The scores arrive already sorted, most coverable first. A provider that
    cannot cover any occurrence never earns the badge even when it lands within
    the first N of a thin list, mirroring the capacity guard on the load path.
    """
    return [
        "recommended" if i < RECOMMENDED_TOP_N and s.available_count > 0 else "other"
        for i, s in enumerate(scores)
    ]


class FirstDateCoverage(NamedTuple):
    first_date: date
    covering_count: int
    candidate_count: int


def providers_covering_series_by_first_date(
    patient_state: str,
    rule: RecurrenceRule,
    window_start: date,
    window_end: date,
    fhir_base_url: str,
    access_token: str,
    tz_offset_minutes: int = 0,
    duration_minutes: int = DEFAULT_DURATION_MINUTES,
    now: datetime | None = None,
) -> list[FirstDateCoverage]:
    """Count, per candidate first date, how many licensed providers have any
    opening for the series starting that day.

    This is the provider agnostic basis for the calendar badge in the when
    before who flow. A day that reads three means three of the candidate
    providers can take at least one occurrence of the series from that start
    date at a shared time, the same providers the card list shows with their
    honest X of N count. A day no provider can start, because the start date has
    no slot for anyone, reads zero, which is the dead end the calendar must stop
    inviting. A provider counts on a day when its best shared start time covers
    at least one occurrence, series_available_count greater than zero, the same
    has_capacity definition the per provider card uses, so the badge equals the
    number of cards that show capacity on that day.

    The candidate first dates depend only on the rule and the window, so they
    are enumerated once and shared across every provider. The license filter
    mirrors the ranking path, an empty patient_state scores every active
    provider. Each provider is scored across the whole window in one memo, so
    the FHIR cost grows with the size of the licensed in state set, not with the
    number of candidate dates.
    """
    today = date.today()
    active_staff = Staff.objects.filter(active=True).prefetch_related("licenses")

    if patient_state:
        matching: list[Staff] = [
            staff
            for staff in active_staff
            if _has_valid_license(staff, patient_state, today)
        ]
    else:
        matching = list(active_staff)

    candidate_first_dates = list(
        iter_candidate_first_dates(rule, window_start, window_end)
    )
    covering: dict[date, int] = {fd: 0 for fd in candidate_first_dates}

    for staff in matching:
        scores = series_scores_by_first_date(
            fhir_base_url=fhir_base_url,
            access_token=access_token,
            provider_id=str(staff.id),
            rule=rule,
            window_start=window_start,
            window_end=window_end,
            tz_offset_minutes=tz_offset_minutes,
            duration_minutes=duration_minutes,
            now=now,
        )
        for s in scores:
            if s.first_date in covering and s.available_count > 0:
                # The Canvas sandbox forbids augmented assignment to a subscript
                # (covering[k] += 1), so rebind explicitly.
                covering[s.first_date] = covering[s.first_date] + 1

    candidate_count = len(matching)
    return [
        FirstDateCoverage(
            first_date=fd,
            covering_count=covering[fd],
            candidate_count=candidate_count,
        )
        for fd in candidate_first_dates
    ]
