from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, call, patch

import pytest


def _make_staff(
    staff_id: str,
    full_name: str,
    npi: str,
    licenses: list[tuple[str, date | None]],
) -> MagicMock:
    """Helper to build a mock Staff with controlled licenses."""
    staff = MagicMock()
    staff.id = staff_id
    staff.full_name = full_name
    staff.npi_number = npi
    staff.active = True

    mock_lics = []
    for state, exp in licenses:
        lic = MagicMock()
        lic.state = state
        lic.expiration_date = exp
        mock_lics.append(lic)

    staff.licenses.all.return_value = mock_lics
    return staff


def _metric(
    pct_filled: float,
    has_capacity: bool = True,
    filled: int = 0,
    free: int = 0,
    total: int | None = None,
):
    """Build a CapacityMetric tuple for use as a mock return value."""
    from scheduling_modal_with_recurring_support.services.capacity import CapacityMetric

    return CapacityMetric(
        pct_filled=pct_filled,
        filled_count=filled,
        free_count=free,
        total_count=total if total is not None else (filled + free),
        has_capacity=has_capacity,
    )


_FHIR_KW = dict(fhir_base_url="https://fhir", access_token="t", location_id="loc")


def _bulk_const(value: int):
    """Build a side_effect for a bulk count helper that returns a constant
    for every staff in the input list."""
    def fn(staff_list, today=None):
        return {str(s.id): value for s in staff_list}
    return fn


def _bulk_from_dict(per_staff: dict):
    """Build a side_effect that resolves counts from a dict keyed by the
    staff mock object."""
    def fn(staff_list, today=None):
        return {str(s.id): per_staff.get(s, 0) for s in staff_list}
    return fn


@pytest.fixture(autouse=True)
def _stub_filled_counts_bulk():
    """Stub the bulk filled-count helper for the whole module.

    The ranking path now pre-counts filled appointments with one grouped query
    and feeds the result to filled_pct_next_window via filled_override. These
    tests patch filled_pct_next_window directly, so the override value is never
    read. This stub only keeps the bulk helper off the real database. Tests that
    need a specific value can still patch the name themselves to override this.
    """
    with patch(
        "scheduling_modal_with_recurring_support.services.provider_filter.filled_counts_next_window_bulk",
        side_effect=_bulk_const(0),
    ):
        yield


def test_licensed_providers_for_state_filters_by_state() -> None:
    from scheduling_modal_with_recurring_support.services.provider_filter import licensed_providers_for_state

    staff_ca = _make_staff("s1", "Dr. CA", "111", [("CA", None)])
    staff_ny = _make_staff("s2", "Dr. NY", "222", [("NY", None)])

    with (
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.filled_pct_next_window",
            return_value=_metric(20.0, has_capacity=True, filled=2, free=8),
        ),
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.appointment_counts_last_30_days_bulk",
            side_effect=_bulk_const(5),
        ) as mock_count_30,
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.upcoming_appointment_counts_7_days_bulk",
            side_effect=_bulk_const(2),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.prefetch_related.return_value = [staff_ca, staff_ny]

        result = licensed_providers_for_state("CA", **_FHIR_KW)

    assert mock_staff_cls.mock_calls == [
        call.objects.filter(active=True),
        call.objects.filter().prefetch_related("licenses"),
    ]
    assert len(result) == 1
    assert result[0].id == "s1"
    assert result[0].full_name == "Dr. CA"
    assert result[0].upcoming_7_days == 2
    assert result[0].tier == "recommended"
    # One bulk call covers every matched staff in a single grouped query.
    assert mock_count_30.call_count == 1
    bulk_call = mock_count_30.call_args
    assert bulk_call.args[0] == [staff_ca]


def test_licensed_providers_skips_expired_license() -> None:
    from scheduling_modal_with_recurring_support.services.provider_filter import licensed_providers_for_state

    yesterday = date.today() - timedelta(days=1)
    staff_expired = _make_staff("s3", "Dr. Expired", "333", [("CA", yesterday)])

    with (
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.filled_pct_next_window",
            return_value=_metric(0.0, has_capacity=False),
        ),
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.appointment_counts_last_30_days_bulk",
            side_effect=_bulk_const(0),
        ) as mock_count,
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.upcoming_appointment_counts_7_days_bulk",
            side_effect=_bulk_const(0),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.prefetch_related.return_value = [staff_expired]

        result = licensed_providers_for_state("CA", **_FHIR_KW)

    assert result == []
    # Bulk count helper is called with the empty matched list, which short
    # circuits inside the helper before any DB work.
    assert mock_count.call_count == 1
    assert mock_count.call_args.args[0] == []


def test_licensed_providers_includes_future_expiry() -> None:
    from scheduling_modal_with_recurring_support.services.provider_filter import licensed_providers_for_state

    tomorrow = date.today() + timedelta(days=1)
    staff_valid = _make_staff("s4", "Dr. Valid", "444", [("CA", tomorrow)])

    with (
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.filled_pct_next_window",
            return_value=_metric(10.0, filled=1, free=9),
        ),
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.appointment_counts_last_30_days_bulk",
            side_effect=_bulk_const(3),
        ) as mock_count,
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.upcoming_appointment_counts_7_days_bulk",
            side_effect=_bulk_const(1),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.prefetch_related.return_value = [staff_valid]

        result = licensed_providers_for_state("CA", **_FHIR_KW)

    assert len(result) == 1
    assert result[0].id == "s4"
    assert result[0].upcoming_7_days == 1
    assert mock_count.call_count == 1
    assert mock_count.call_args.args[0] == [staff_valid]


def test_licensed_providers_sorted_by_upcoming_load() -> None:
    from scheduling_modal_with_recurring_support.services.provider_filter import licensed_providers_for_state

    heavy = _make_staff("s5", "Dr. Heavy", "555", [("CA", None)])
    light = _make_staff("s6", "Dr. Light", "666", [("CA", None)])

    counts_30 = {heavy: 20, light: 3}
    counts_7 = {heavy: 10, light: 1}
    metrics = {heavy: _metric(80.0, filled=8, free=2), light: _metric(20.0, filled=1, free=4)}

    with (
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.filled_pct_next_window",
            side_effect=lambda s, **kw: metrics[s],
        ),
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.appointment_counts_last_30_days_bulk",
            side_effect=_bulk_from_dict(counts_30),
        ),
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.upcoming_appointment_counts_7_days_bulk",
            side_effect=_bulk_from_dict(counts_7),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.prefetch_related.return_value = [heavy, light]

        result = licensed_providers_for_state("CA", **_FHIR_KW)

    assert result[0].id == "s6"
    assert result[0].upcoming_7_days == 1
    assert result[1].id == "s5"
    assert result[1].upcoming_7_days == 10


def test_empty_state_returns_no_providers() -> None:
    from scheduling_modal_with_recurring_support.services.provider_filter import licensed_providers_for_state

    staff_ca = _make_staff("s7", "Dr. CA2", "777", [("CA", None)])

    with (
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.filled_pct_next_window",
            return_value=_metric(0.0, has_capacity=False),
        ),
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.appointment_counts_last_30_days_bulk",
            side_effect=_bulk_const(0),
        ) as mock_count,
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.upcoming_appointment_counts_7_days_bulk",
            side_effect=_bulk_const(0),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.prefetch_related.return_value = [staff_ca]

        result = licensed_providers_for_state("TX", **_FHIR_KW)

    assert result == []
    assert mock_count.call_count == 1
    assert mock_count.call_args.args[0] == []


def test_empty_patient_state_skips_license_filter() -> None:
    """When patient_state is empty, return every active provider without applying the license filter."""
    from scheduling_modal_with_recurring_support.services.provider_filter import licensed_providers_for_state

    staff_ca = _make_staff("s1", "Dr. CA", "111", [("CA", None)])
    staff_ny = _make_staff("s2", "Dr. NY", "222", [("NY", None)])
    staff_no_license = _make_staff("s3", "Dr. None", "333", [])

    with (
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.filled_pct_next_window",
            return_value=_metric(25.0),
        ),
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.appointment_counts_last_30_days_bulk",
            side_effect=_bulk_const(1),
        ),
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.upcoming_appointment_counts_7_days_bulk",
            side_effect=_bulk_const(1),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.prefetch_related.return_value = [
            staff_ca,
            staff_ny,
            staff_no_license,
        ]

        result = licensed_providers_for_state("", **_FHIR_KW)

    # All three providers come back regardless of license state.
    assert {p.id for p in result} == {"s1", "s2", "s3"}


def test_tier_assignment_recommended_vs_other() -> None:
    from scheduling_modal_with_recurring_support.services.provider_filter import licensed_providers_for_state

    s1 = _make_staff("a", "Dr. A", "111", [("CA", None)])
    s2 = _make_staff("b", "Dr. B", "222", [("CA", None)])
    s3 = _make_staff("c", "Dr. C", "333", [("CA", None)])
    s4 = _make_staff("d", "Dr. D", "444", [("CA", None)])

    upcoming = {s1: 2, s2: 5, s3: 1, s4: 8}
    metrics = {
        s1: _metric(20.0, filled=2, free=8),
        s2: _metric(50.0, filled=5, free=5),
        s3: _metric(10.0, filled=1, free=9),
        s4: _metric(80.0, filled=8, free=2),
    }

    with (
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.filled_pct_next_window",
            side_effect=lambda s, **kw: metrics[s],
        ),
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.appointment_counts_last_30_days_bulk",
            side_effect=_bulk_const(0),
        ),
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.upcoming_appointment_counts_7_days_bulk",
            side_effect=_bulk_from_dict(upcoming),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.prefetch_related.return_value = [s1, s2, s3, s4]

        result = licensed_providers_for_state("CA", **_FHIR_KW)

    # Top three by availability earn the badge, the fourth drops to other.
    assert [r.tier for r in result] == ["recommended", "recommended", "recommended", "other"]
    assert [r.upcoming_7_days for r in result] == [1, 2, 5, 8]


def test_tier_all_recommended_when_two_or_fewer() -> None:
    from scheduling_modal_with_recurring_support.services.provider_filter import licensed_providers_for_state

    s1 = _make_staff("a", "Dr. A", "111", [("CA", None)])
    s2 = _make_staff("b", "Dr. B", "222", [("CA", None)])

    with (
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.filled_pct_next_window",
            return_value=_metric(30.0, filled=3, free=7),
        ),
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.appointment_counts_last_30_days_bulk",
            side_effect=_bulk_const(0),
        ),
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.upcoming_appointment_counts_7_days_bulk",
            side_effect=_bulk_const(3),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.prefetch_related.return_value = [s1, s2]

        result = licensed_providers_for_state("CA", **_FHIR_KW)

    assert all(r.tier == "recommended" for r in result)


# ---- New cases for Gap A ----


def test_licensed_providers_sorted_by_pct_filled_ascending() -> None:
    from scheduling_modal_with_recurring_support.services.provider_filter import licensed_providers_for_state

    a = _make_staff("a", "Dr. Eighty", "111", [("CA", None)])
    b = _make_staff("b", "Dr. TwentyFive", "222", [("CA", None)])
    c = _make_staff("c", "Dr. Fifty", "333", [("CA", None)])

    metrics = {
        a: _metric(80.0, filled=8, free=2),
        b: _metric(25.0, filled=2, free=6),
        c: _metric(50.0, filled=5, free=5),
    }

    with (
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.filled_pct_next_window",
            side_effect=lambda s, **kw: metrics[s],
        ),
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.appointment_counts_last_30_days_bulk",
            side_effect=_bulk_const(0),
        ),
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.upcoming_appointment_counts_7_days_bulk",
            side_effect=_bulk_const(0),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.prefetch_related.return_value = [a, b, c]

        result = licensed_providers_for_state("CA", **_FHIR_KW)

    assert [r.pct_filled for r in result] == [25.0, 50.0, 80.0]
    assert [r.id for r in result] == ["b", "c", "a"]


def test_zero_capacity_providers_sort_to_bottom() -> None:
    from scheduling_modal_with_recurring_support.services.provider_filter import licensed_providers_for_state

    busy = _make_staff("a", "Dr. Sixty", "111", [("CA", None)])
    empty = _make_staff("b", "Dr. Empty", "222", [("CA", None)])
    light = _make_staff("c", "Dr. Thirty", "333", [("CA", None)])

    metrics = {
        busy: _metric(60.0, has_capacity=True, filled=6, free=4),
        empty: _metric(0.0, has_capacity=False, filled=0, free=0),
        light: _metric(30.0, has_capacity=True, filled=3, free=7),
    }

    with (
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.filled_pct_next_window",
            side_effect=lambda s, **kw: metrics[s],
        ),
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.appointment_counts_last_30_days_bulk",
            side_effect=_bulk_const(0),
        ),
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.upcoming_appointment_counts_7_days_bulk",
            side_effect=_bulk_const(0),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.prefetch_related.return_value = [busy, empty, light]

        result = licensed_providers_for_state("CA", **_FHIR_KW)

    assert [r.id for r in result] == ["c", "a", "b"]
    assert result[-1].has_capacity is False


def test_provider_summary_carries_metric_fields() -> None:
    from scheduling_modal_with_recurring_support.services.provider_filter import licensed_providers_for_state

    s = _make_staff("a", "Dr. Solo", "111", [("CA", None)])
    metric = _metric(40.0, has_capacity=True, filled=4, free=6)

    with (
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.filled_pct_next_window",
            return_value=metric,
        ),
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.appointment_counts_last_30_days_bulk",
            side_effect=_bulk_const(0),
        ),
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.upcoming_appointment_counts_7_days_bulk",
            side_effect=_bulk_const(0),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.prefetch_related.return_value = [s]

        result = licensed_providers_for_state("CA", **_FHIR_KW)

    assert result[0].pct_filled == 40.0
    assert result[0].filled_count == 4
    assert result[0].free_count == 6
    assert result[0].total_count == 10
    assert result[0].has_capacity is True


# ---- New cases for the top N recommended rule ----


def _tier_for(metric) -> str:
    from scheduling_modal_with_recurring_support.services.provider_filter import licensed_providers_for_state

    s = _make_staff("a", "Dr. Solo", "111", [("CA", None)])

    with (
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.filled_pct_next_window",
            return_value=metric,
        ),
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.appointment_counts_last_30_days_bulk",
            side_effect=_bulk_const(0),
        ),
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.upcoming_appointment_counts_7_days_bulk",
            side_effect=_bulk_const(0),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.prefetch_related.return_value = [s]

        result = licensed_providers_for_state("CA", **_FHIR_KW)

    return result[0].tier


def test_tier_recommended_lone_provider_within_top_n() -> None:
    """A single provider with capacity sits within the top three, so recommended."""
    assert _tier_for(_metric(40.0, has_capacity=True, filled=4, free=6)) == "recommended"


def test_tier_recommended_ignores_high_fill_within_top_n() -> None:
    """Rank decides the badge, not the fill level. A provider in the top three
    earns recommended even when it is well above the old fifty percent line."""
    assert _tier_for(_metric(60.0, has_capacity=True, filled=6, free=4)) == "recommended"


def test_tier_other_when_zero_capacity() -> None:
    """The capacity guard holds. A provider with no capacity never earns the
    badge even when it lands within the first three slots."""
    assert _tier_for(_metric(0.0, has_capacity=False, filled=0, free=0)) == "other"


def test_tier_capacity_guard_within_top_three() -> None:
    """Two providers have capacity, two do not. The zero capacity providers
    sort to the bottom, and the one landing in the third slot still reads
    other because the guard overrides rank."""
    from scheduling_modal_with_recurring_support.services.provider_filter import licensed_providers_for_state

    s1 = _make_staff("a", "Dr. Open", "111", [("CA", None)])
    s2 = _make_staff("b", "Dr. Light", "222", [("CA", None)])
    s3 = _make_staff("c", "Dr. Full", "333", [("CA", None)])
    s4 = _make_staff("d", "Dr. Empty", "444", [("CA", None)])

    metrics = {
        s1: _metric(20.0, has_capacity=True, filled=2, free=8),
        s2: _metric(40.0, has_capacity=True, filled=4, free=6),
        s3: _metric(0.0, has_capacity=False, filled=0, free=0),
        s4: _metric(0.0, has_capacity=False, filled=0, free=0),
    }

    with (
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.filled_pct_next_window",
            side_effect=lambda s, **kw: metrics[s],
        ),
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.appointment_counts_last_30_days_bulk",
            side_effect=_bulk_const(0),
        ),
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.upcoming_appointment_counts_7_days_bulk",
            side_effect=_bulk_const(0),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.prefetch_related.return_value = [s1, s2, s3, s4]

        result = licensed_providers_for_state("CA", **_FHIR_KW)

    # Only the two with capacity earn the badge, the zero capacity provider in
    # the third slot lands in other despite its rank.
    assert [r.tier for r in result] == ["recommended", "recommended", "other", "other"]


# ---- providers_ranked_by_series_availability (date aware ranking) ----


def _series(available: int, total: int, best_hhmm: str = "09:00"):
    """Build a SeriesScore for use as a best_series_availability return."""
    from scheduling_modal_with_recurring_support.services.availability import SeriesScore

    return SeriesScore(available_count=available, total_count=total, best_hhmm=best_hhmm)


def _rule():
    from scheduling_modal_with_recurring_support.services.recurrence import from_legacy_cadence

    return from_legacy_cadence("weekly", 5)


_RANK_KW = dict(
    fhir_base_url="https://fhir",
    access_token="t",
    tz_offset_minutes=240,
    duration_minutes=60,
)


def _by_provider(per_staff: dict):
    """Side effect that resolves a SeriesScore from a dict keyed by staff id."""
    def fn(*, provider_id, **kwargs):
        return per_staff[provider_id]
    return fn


def test_ranked_sorts_by_real_series_availability_desc() -> None:
    from scheduling_modal_with_recurring_support.services.provider_filter import (
        providers_ranked_by_series_availability,
    )

    low = _make_staff("a", "Dr. Low", "111", [("CA", None)])
    high = _make_staff("b", "Dr. High", "222", [("CA", None)])
    mid = _make_staff("c", "Dr. Mid", "333", [("CA", None)])

    scores = {"a": _series(1, 5), "b": _series(5, 5), "c": _series(3, 5)}

    with (
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.best_series_availability",
            side_effect=_by_provider(scores),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.prefetch_related.return_value = [low, high, mid]

        result = providers_ranked_by_series_availability("CA", _rule(), date(2026, 5, 1), **_RANK_KW)

    assert [r.id for r in result] == ["b", "c", "a"]
    assert [r.series_available_count for r in result] == [5, 3, 1]
    assert result[0].series_total_count == 5
    assert result[0].best_hhmm == "09:00"


def test_ranked_zero_coverage_sinks_and_never_recommended() -> None:
    from scheduling_modal_with_recurring_support.services.provider_filter import (
        providers_ranked_by_series_availability,
    )

    open_a = _make_staff("a", "Dr. Open A", "111", [("CA", None)])
    open_b = _make_staff("b", "Dr. Open B", "222", [("CA", None)])
    closed = _make_staff("c", "Dr. Closed", "333", [("CA", None)])

    # Three providers, only two can cover any occurrence. The closed provider
    # scored zero on a closed start date sinks to the bottom and stays other
    # even though it lands within the top three of a thin list.
    scores = {"a": _series(4, 5), "b": _series(2, 5), "c": _series(0, 5, "")}

    with (
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.best_series_availability",
            side_effect=_by_provider(scores),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.prefetch_related.return_value = [open_a, open_b, closed]

        result = providers_ranked_by_series_availability("CA", _rule(), date(2026, 5, 1), **_RANK_KW)

    assert [r.id for r in result] == ["a", "b", "c"]
    assert [r.tier for r in result] == ["recommended", "recommended", "other"]
    assert result[-1].has_capacity is False


def test_ranked_top_three_recommended_rest_other() -> None:
    from scheduling_modal_with_recurring_support.services.provider_filter import (
        providers_ranked_by_series_availability,
    )

    s1 = _make_staff("a", "Dr. A", "111", [("CA", None)])
    s2 = _make_staff("b", "Dr. B", "222", [("CA", None)])
    s3 = _make_staff("c", "Dr. C", "333", [("CA", None)])
    s4 = _make_staff("d", "Dr. D", "444", [("CA", None)])

    scores = {"a": _series(5, 5), "b": _series(4, 5), "c": _series(3, 5), "d": _series(2, 5)}

    with (
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.best_series_availability",
            side_effect=_by_provider(scores),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.prefetch_related.return_value = [s1, s2, s3, s4]

        result = providers_ranked_by_series_availability("CA", _rule(), date(2026, 5, 1), **_RANK_KW)

    assert [r.tier for r in result] == ["recommended", "recommended", "recommended", "other"]


def test_ranked_ties_break_by_name() -> None:
    from scheduling_modal_with_recurring_support.services.provider_filter import (
        providers_ranked_by_series_availability,
    )

    zeb = _make_staff("a", "Dr. Zeb", "111", [("CA", None)])
    abe = _make_staff("b", "Dr. Abe", "222", [("CA", None)])

    scores = {"a": _series(3, 5), "b": _series(3, 5)}

    with (
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.best_series_availability",
            side_effect=_by_provider(scores),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.prefetch_related.return_value = [zeb, abe]

        result = providers_ranked_by_series_availability("CA", _rule(), date(2026, 5, 1), **_RANK_KW)

    # Equal coverage falls back to name order, Abe before Zeb.
    assert [r.full_name for r in result] == ["Dr. Abe", "Dr. Zeb"]


def test_ranked_filters_by_license_state() -> None:
    from scheduling_modal_with_recurring_support.services.provider_filter import (
        providers_ranked_by_series_availability,
    )

    ca = _make_staff("a", "Dr. CA", "111", [("CA", None)])
    ny = _make_staff("b", "Dr. NY", "222", [("NY", None)])

    scores = {"a": _series(4, 5), "b": _series(5, 5)}

    with (
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.best_series_availability",
            side_effect=_by_provider(scores),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.prefetch_related.return_value = [ca, ny]

        result = providers_ranked_by_series_availability("CA", _rule(), date(2026, 5, 1), **_RANK_KW)

    # Only the CA licensed provider survives the filter.
    assert [r.id for r in result] == ["a"]


def test_ranked_empty_state_scores_every_active_provider() -> None:
    from scheduling_modal_with_recurring_support.services.provider_filter import (
        providers_ranked_by_series_availability,
    )

    ca = _make_staff("a", "Dr. CA", "111", [("CA", None)])
    ny = _make_staff("b", "Dr. NY", "222", [("NY", None)])
    none = _make_staff("c", "Dr. None", "333", [])

    scores = {"a": _series(1, 5), "b": _series(2, 5), "c": _series(3, 5)}

    with (
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.best_series_availability",
            side_effect=_by_provider(scores),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.prefetch_related.return_value = [ca, ny, none]

        result = providers_ranked_by_series_availability("", _rule(), date(2026, 5, 1), **_RANK_KW)

    assert {r.id for r in result} == {"a", "b", "c"}


# ---- providers_covering_series_by_first_date (provider agnostic badge) ----


def _cov_window():
    """A weekly count 3 rule over a two day window, so the real
    iter_candidate_first_dates yields exactly May 4 and May 5."""
    from scheduling_modal_with_recurring_support.services.recurrence import (
        from_legacy_cadence,
        iter_candidate_first_dates,
    )

    rule = from_legacy_cadence("weekly", 3)
    window_start = date(2026, 5, 4)
    window_end = date(2026, 5, 5)
    first_dates = list(iter_candidate_first_dates(rule, window_start, window_end))
    return rule, window_start, window_end, first_dates


def _scores_for(first_dates, pairs):
    """Build a per first date score list. pairs is [(available, total), ...]
    aligned to first_dates."""
    from scheduling_modal_with_recurring_support.services.availability import (
        FirstDateSeriesScore,
    )

    return [
        FirstDateSeriesScore(
            first_date=fd, available_count=a, total_count=t, best_hhmm="09:00"
        )
        for fd, (a, t) in zip(first_dates, pairs)
    ]


_COV_KW = dict(fhir_base_url="https://fhir", access_token="t", tz_offset_minutes=240)


def test_covering_counts_any_capacity_per_first_date() -> None:
    from scheduling_modal_with_recurring_support.services.provider_filter import (
        providers_covering_series_by_first_date,
    )

    rule, ws, we, first_dates = _cov_window()
    assert first_dates == [date(2026, 5, 4), date(2026, 5, 5)]

    a = _make_staff("a", "Dr. A", "111", [("CA", None)])
    b = _make_staff("b", "Dr. B", "222", [("CA", None)])

    # The badge counts any capacity now, a provider counts on a day when its
    # best shared time covers at least one occurrence. A has a partial three of
    # five on May 4 and zero on May 5. B has openings on both days. So May 4
    # reads two providers, the partial A included, and May 5 reads one.
    per_provider = {
        "a": _scores_for(first_dates, [(3, 5), (0, 5)]),
        "b": _scores_for(first_dates, [(5, 5), (2, 5)]),
    }

    def fake_scores(*, provider_id, **kwargs):
        return per_provider[provider_id]

    with (
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.series_scores_by_first_date",
            side_effect=fake_scores,
        ),
    ):
        mock_staff_cls.objects.filter.return_value.prefetch_related.return_value = [a, b]

        result = providers_covering_series_by_first_date("CA", rule, ws, we, **_COV_KW)

    by = {c.first_date: c for c in result}
    assert by[date(2026, 5, 4)].covering_count == 2
    assert by[date(2026, 5, 5)].covering_count == 1
    assert all(c.candidate_count == 2 for c in result)


def test_covering_day_with_no_starter_reads_zero() -> None:
    from scheduling_modal_with_recurring_support.services.provider_filter import (
        providers_covering_series_by_first_date,
    )

    rule, ws, we, first_dates = _cov_window()

    a = _make_staff("a", "Dr. A", "111", [("CA", None)])

    # The only provider cannot start the series on May 5 (zero of three), so
    # that day reads zero even though it is a candidate first date.
    per_provider = {"a": _scores_for(first_dates, [(3, 3), (0, 3)])}

    def fake_scores(*, provider_id, **kwargs):
        return per_provider[provider_id]

    with (
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.series_scores_by_first_date",
            side_effect=fake_scores,
        ),
    ):
        mock_staff_cls.objects.filter.return_value.prefetch_related.return_value = [a]

        result = providers_covering_series_by_first_date("CA", rule, ws, we, **_COV_KW)

    by = {c.first_date: c for c in result}
    assert by[date(2026, 5, 4)].covering_count == 1
    assert by[date(2026, 5, 5)].covering_count == 0


def test_covering_applies_license_filter() -> None:
    from scheduling_modal_with_recurring_support.services.provider_filter import (
        providers_covering_series_by_first_date,
    )

    rule, ws, we, first_dates = _cov_window()

    ca = _make_staff("a", "Dr. CA", "111", [("CA", None)])
    ny = _make_staff("b", "Dr. NY", "222", [("NY", None)])

    scored_ids: list[str] = []

    def fake_scores(*, provider_id, **kwargs):
        scored_ids.append(provider_id)
        return _scores_for(first_dates, [(3, 3), (3, 3)])

    with (
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.series_scores_by_first_date",
            side_effect=fake_scores,
        ),
    ):
        mock_staff_cls.objects.filter.return_value.prefetch_related.return_value = [ca, ny]

        result = providers_covering_series_by_first_date("CA", rule, ws, we, **_COV_KW)

    # Only the CA licensed provider is scored and counted.
    assert scored_ids == ["a"]
    assert all(c.candidate_count == 1 for c in result)
    assert {c.covering_count for c in result} == {1}


def test_covering_no_matching_providers_returns_zeroed_candidates() -> None:
    from scheduling_modal_with_recurring_support.services.provider_filter import (
        providers_covering_series_by_first_date,
    )

    rule, ws, we, first_dates = _cov_window()

    ny = _make_staff("b", "Dr. NY", "222", [("NY", None)])

    with (
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.Staff"
        ) as mock_staff_cls,
        patch(
            "scheduling_modal_with_recurring_support.services.provider_filter.series_scores_by_first_date",
            side_effect=AssertionError("no provider should be scored"),
        ),
    ):
        mock_staff_cls.objects.filter.return_value.prefetch_related.return_value = [ny]

        result = providers_covering_series_by_first_date("CA", rule, ws, we, **_COV_KW)

    # No CA provider, so the calendar still enumerates the candidate days, each
    # covered by zero of zero candidates rather than collapsing to an empty list.
    assert [c.first_date for c in result] == first_dates
    assert all(c.covering_count == 0 and c.candidate_count == 0 for c in result)
