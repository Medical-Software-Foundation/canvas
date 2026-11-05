from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, call, patch


def _make_cache_mock(get_returns=None) -> MagicMock:
    cache = MagicMock()
    cache.get.return_value = get_returns
    return cache


# ---- filled_pct_next_window ----


def test_filled_pct_zero_total_returns_no_capacity() -> None:
    from scheduling_modal_with_recurring_support.services.capacity import filled_pct_next_window

    mock_staff = MagicMock()
    mock_staff.id = 1

    with (
        patch("scheduling_modal_with_recurring_support.services.capacity.Appointment") as mock_appt_cls,
        patch(
            "scheduling_modal_with_recurring_support.services.capacity._count_free_slots",
            return_value=0,
        ) as mock_free,
        patch(
            "scheduling_modal_with_recurring_support.services.capacity.get_cache",
            return_value=_make_cache_mock(),
        ),
    ):
        mock_appt_cls.objects.filter.return_value.exclude.return_value.count.return_value = 0

        metric = filled_pct_next_window(mock_staff, "https://fhir", "token", "loc-1")

    assert metric.pct_filled == 0.0
    assert metric.filled_count == 0
    assert metric.free_count == 0
    assert metric.total_count == 0
    assert metric.has_capacity is False
    assert mock_free.called


def test_filled_pct_partial_capacity() -> None:
    from scheduling_modal_with_recurring_support.services.capacity import filled_pct_next_window

    mock_staff = MagicMock()
    mock_staff.id = 2

    with (
        patch("scheduling_modal_with_recurring_support.services.capacity.Appointment") as mock_appt_cls,
        patch(
            "scheduling_modal_with_recurring_support.services.capacity._count_free_slots",
            return_value=6,
        ),
        patch(
            "scheduling_modal_with_recurring_support.services.capacity.get_cache",
            return_value=_make_cache_mock(),
        ),
    ):
        mock_appt_cls.objects.filter.return_value.exclude.return_value.count.return_value = 2

        metric = filled_pct_next_window(mock_staff, "https://fhir", "token", "loc-1")

    assert metric.pct_filled == 25.0
    assert metric.filled_count == 2
    assert metric.free_count == 6
    assert metric.total_count == 8
    assert metric.has_capacity is True


def test_filled_pct_fully_booked() -> None:
    from scheduling_modal_with_recurring_support.services.capacity import filled_pct_next_window

    mock_staff = MagicMock()
    mock_staff.id = 3

    with (
        patch("scheduling_modal_with_recurring_support.services.capacity.Appointment") as mock_appt_cls,
        patch(
            "scheduling_modal_with_recurring_support.services.capacity._count_free_slots",
            return_value=0,
        ),
        patch(
            "scheduling_modal_with_recurring_support.services.capacity.get_cache",
            return_value=_make_cache_mock(),
        ),
    ):
        mock_appt_cls.objects.filter.return_value.exclude.return_value.count.return_value = 8

        metric = filled_pct_next_window(mock_staff, "https://fhir", "token", "loc-1")

    assert metric.pct_filled == 100.0
    assert metric.filled_count == 8
    assert metric.free_count == 0
    assert metric.has_capacity is True


def test_filled_pct_uses_cache_hit() -> None:
    from scheduling_modal_with_recurring_support.services.capacity import filled_pct_next_window

    mock_staff = MagicMock()
    mock_staff.id = 4

    cached_tuple = (50.0, 4, 4, 8, True)
    cache_mock = _make_cache_mock(get_returns=cached_tuple)

    with (
        patch("scheduling_modal_with_recurring_support.services.capacity.Appointment") as mock_appt_cls,
        patch(
            "scheduling_modal_with_recurring_support.services.capacity._count_free_slots",
        ) as mock_free,
        patch(
            "scheduling_modal_with_recurring_support.services.capacity.get_cache",
            return_value=cache_mock,
        ),
    ):
        metric = filled_pct_next_window(mock_staff, "https://fhir", "token", "loc-1")

    assert tuple(metric) == cached_tuple
    assert mock_appt_cls.mock_calls == []
    assert mock_free.called is False
    assert cache_mock.set.called is False


def test_filled_pct_writes_cache_on_miss() -> None:
    from scheduling_modal_with_recurring_support.services.capacity import (
        CACHE_TTL_SECONDS,
        filled_pct_next_window,
    )

    mock_staff = MagicMock()
    mock_staff.id = 5

    cache_mock = _make_cache_mock()

    fixed_today = date(2026, 4, 28)

    with (
        patch("scheduling_modal_with_recurring_support.services.capacity.Appointment") as mock_appt_cls,
        patch(
            "scheduling_modal_with_recurring_support.services.capacity._count_free_slots",
            return_value=3,
        ),
        patch(
            "scheduling_modal_with_recurring_support.services.capacity.get_cache",
            return_value=cache_mock,
        ),
    ):
        mock_appt_cls.objects.filter.return_value.exclude.return_value.count.return_value = 1

        filled_pct_next_window(
            mock_staff,
            "https://fhir",
            "token",
            "loc-1",
            today=fixed_today,
        )

    expected_key = "cnv898:filled_pct:5:2026-04-28:30"
    cache_mock.set.assert_called_once()
    args, _ = cache_mock.set.call_args
    assert args[0] == expected_key
    assert args[1] == (25.0, 1, 3, 4, True)
    assert args[2] == CACHE_TTL_SECONDS


def test_filled_pct_excludes_cancelled() -> None:
    from scheduling_modal_with_recurring_support.services.capacity import filled_pct_next_window

    mock_staff = MagicMock()
    mock_staff.id = 6

    with (
        patch("scheduling_modal_with_recurring_support.services.capacity.Appointment") as mock_appt_cls,
        patch(
            "scheduling_modal_with_recurring_support.services.capacity._count_free_slots",
            return_value=2,
        ),
        patch(
            "scheduling_modal_with_recurring_support.services.capacity.get_cache",
            return_value=_make_cache_mock(),
        ),
    ):
        mock_appt_cls.objects.filter.return_value.exclude.return_value.count.return_value = 1

        filled_pct_next_window(mock_staff, "https://fhir", "token", "loc-1")

    mock_appt_cls.objects.filter.return_value.exclude.assert_called_with(status="cancelled")


# ---- bust_filled_pct ----


def test_bust_filled_pct_deletes_correct_key() -> None:
    from scheduling_modal_with_recurring_support.services.capacity import bust_filled_pct

    cache_mock = MagicMock()

    with patch(
        "scheduling_modal_with_recurring_support.services.capacity.get_cache",
        return_value=cache_mock,
    ):
        bust_filled_pct("staff-id-1", today=date(2026, 4, 28))

    cache_mock.delete.assert_called_once_with("cnv898:filled_pct:staff-id-1:2026-04-28:30")


# ---- Bulk count helpers ----
#
# A per provider count would run one Appointment.objects.filter for every
# provider in the licensed list. On a fifty provider tenant the cold path was
# 100 DB queries. These bulk helpers collapse each window into one grouped
# query keyed by staff id.


def test_appointment_counts_last_30_days_bulk_groups_into_one_query() -> None:
    from scheduling_modal_with_recurring_support.services.capacity import (
        appointment_counts_last_30_days_bulk,
    )

    staff_a = MagicMock()
    staff_a.id = "a"
    staff_b = MagicMock()
    staff_b.id = "b"
    today = date(2026, 5, 1)
    thirty_days_ago = today - timedelta(days=30)

    with patch(
        "scheduling_modal_with_recurring_support.services.capacity.Appointment"
    ) as mock_appt_cls:
        mock_appt_cls.objects.filter.return_value.values.return_value.annotate.return_value = [
            {"provider": "a", "count": 3},
            {"provider": "b", "count": 5},
        ]
        result = appointment_counts_last_30_days_bulk([staff_a, staff_b], today=today)

    assert result == {"a": 3, "b": 5}
    mock_appt_cls.objects.filter.assert_called_once_with(
        provider__in=[staff_a, staff_b],
        start_time__date__gte=thirty_days_ago,
        start_time__date__lt=today,
    )
    mock_appt_cls.objects.filter.return_value.values.assert_called_once_with("provider")


def test_appointment_counts_last_30_days_bulk_empty_returns_empty_dict() -> None:
    from scheduling_modal_with_recurring_support.services.capacity import (
        appointment_counts_last_30_days_bulk,
    )

    with patch(
        "scheduling_modal_with_recurring_support.services.capacity.Appointment"
    ) as mock_appt_cls:
        result = appointment_counts_last_30_days_bulk([])

    assert result == {}
    mock_appt_cls.objects.filter.assert_not_called()


def test_appointment_counts_last_30_days_bulk_defaults_missing_staff_to_zero() -> None:
    from scheduling_modal_with_recurring_support.services.capacity import (
        appointment_counts_last_30_days_bulk,
    )

    staff_a = MagicMock()
    staff_a.id = "a"
    staff_b = MagicMock()
    staff_b.id = "b"

    with patch(
        "scheduling_modal_with_recurring_support.services.capacity.Appointment"
    ) as mock_appt_cls:
        mock_appt_cls.objects.filter.return_value.values.return_value.annotate.return_value = [
            {"provider": "a", "count": 3},
        ]
        result = appointment_counts_last_30_days_bulk([staff_a, staff_b])

    assert result == {"a": 3, "b": 0}


def test_upcoming_appointment_counts_7_days_bulk_groups_into_one_query() -> None:
    from scheduling_modal_with_recurring_support.services.capacity import (
        upcoming_appointment_counts_7_days_bulk,
    )

    staff_a = MagicMock()
    staff_a.id = "a"
    staff_b = MagicMock()
    staff_b.id = "b"
    today = date(2026, 5, 1)
    seven_days = today + timedelta(days=7)

    with patch(
        "scheduling_modal_with_recurring_support.services.capacity.Appointment"
    ) as mock_appt_cls:
        mock_appt_cls.objects.filter.return_value.values.return_value.annotate.return_value = [
            {"provider": "a", "count": 2},
            {"provider": "b", "count": 4},
        ]
        result = upcoming_appointment_counts_7_days_bulk([staff_a, staff_b], today=today)

    assert result == {"a": 2, "b": 4}
    mock_appt_cls.objects.filter.assert_called_once_with(
        provider__in=[staff_a, staff_b],
        start_time__date__gte=today,
        start_time__date__lte=seven_days,
    )


def test_upcoming_appointment_counts_7_days_bulk_empty_returns_empty_dict() -> None:
    from scheduling_modal_with_recurring_support.services.capacity import (
        upcoming_appointment_counts_7_days_bulk,
    )

    with patch(
        "scheduling_modal_with_recurring_support.services.capacity.Appointment"
    ) as mock_appt_cls:
        result = upcoming_appointment_counts_7_days_bulk([])

    assert result == {}
    mock_appt_cls.objects.filter.assert_not_called()


def test_filled_counts_next_window_bulk_groups_into_one_query() -> None:
    from scheduling_modal_with_recurring_support.services.capacity import (
        WINDOW_DAYS,
        filled_counts_next_window_bulk,
    )

    staff_a = MagicMock()
    staff_a.id = "a"
    staff_b = MagicMock()
    staff_b.id = "b"
    today = date(2026, 5, 1)
    window_end = today + timedelta(days=WINDOW_DAYS)

    with patch(
        "scheduling_modal_with_recurring_support.services.capacity.Appointment"
    ) as mock_appt_cls:
        annotate = (
            mock_appt_cls.objects.filter.return_value.exclude.return_value.values.return_value.annotate
        )
        annotate.return_value = [
            {"provider": "a", "count": 6},
            {"provider": "b", "count": 1},
        ]
        result = filled_counts_next_window_bulk([staff_a, staff_b], today=today)

    assert result == {"a": 6, "b": 1}
    mock_appt_cls.objects.filter.assert_called_once_with(
        provider__in=[staff_a, staff_b],
        start_time__date__gte=today,
        start_time__date__lt=window_end,
    )
    mock_appt_cls.objects.filter.return_value.exclude.assert_called_once_with(
        status="cancelled"
    )


def test_filled_counts_next_window_bulk_empty_returns_empty_dict() -> None:
    from scheduling_modal_with_recurring_support.services.capacity import (
        filled_counts_next_window_bulk,
    )

    with patch(
        "scheduling_modal_with_recurring_support.services.capacity.Appointment"
    ) as mock_appt_cls:
        result = filled_counts_next_window_bulk([])

    assert result == {}
    mock_appt_cls.objects.filter.assert_not_called()


def test_filled_counts_next_window_bulk_defaults_missing_staff_to_zero() -> None:
    from scheduling_modal_with_recurring_support.services.capacity import (
        filled_counts_next_window_bulk,
    )

    staff_a = MagicMock()
    staff_a.id = "a"
    staff_b = MagicMock()
    staff_b.id = "b"

    with patch(
        "scheduling_modal_with_recurring_support.services.capacity.Appointment"
    ) as mock_appt_cls:
        annotate = (
            mock_appt_cls.objects.filter.return_value.exclude.return_value.values.return_value.annotate
        )
        annotate.return_value = [{"provider": "a", "count": 6}]
        result = filled_counts_next_window_bulk([staff_a, staff_b])

    assert result == {"a": 6, "b": 0}


def test_filled_pct_uses_filled_override_and_skips_count_query() -> None:
    from scheduling_modal_with_recurring_support.services.capacity import (
        filled_pct_next_window,
    )

    staff = MagicMock()
    staff.id = "a"
    cache = _make_cache_mock(get_returns=None)

    with (
        patch(
            "scheduling_modal_with_recurring_support.services.capacity.get_cache",
            return_value=cache,
        ),
        patch(
            "scheduling_modal_with_recurring_support.services.capacity.Appointment"
        ) as mock_appt_cls,
        patch(
            "scheduling_modal_with_recurring_support.services.capacity._count_free_slots",
            return_value=4,
        ),
    ):
        metric = filled_pct_next_window(
            staff,
            "https://fhir",
            "token",
            "loc-1",
            filled_override=6,
        )

    assert metric.filled_count == 6
    assert metric.free_count == 4
    assert metric.total_count == 10
    assert metric.pct_filled == 60.0
    mock_appt_cls.objects.filter.assert_not_called()
