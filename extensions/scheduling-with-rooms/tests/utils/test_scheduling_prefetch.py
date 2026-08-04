"""Tests for the bulk prefetch helpers that keep the month view off N+1 queries.

Kept separate from ``test_scheduling_logic.py``, which stubs these out.
"""

import datetime
from unittest.mock import patch

from scheduling_with_rooms.models.staff_slot_config import prefetch_concurrent_limits
from scheduling_with_rooms.utils.scheduling_logic import (
    _get_blocking_appointments,
    build_month_slot_counts,
    prefetch_blocking_appointments,
)

LOGIC = "scheduling_with_rooms.utils.scheduling_logic"
CONFIG = "scheduling_with_rooms.models.staff_slot_config"

UTC = datetime.timezone.utc


# prefetch_concurrent_limits --------------------------------------------

def _configured(rows):
    """Patch StaffSlotConfig to return the given (staff_key, limit) rows."""
    patcher = patch(f"{CONFIG}.StaffSlotConfig")
    mock = patcher.start()
    mock.objects.filter.return_value.values_list.return_value = rows
    return patcher, mock


def test_prefetch_limits_returns_an_entry_for_every_key():
    patcher, mock = _configured([("s1", 5)])
    try:
        result = prefetch_concurrent_limits(["s1", "s2"])

        # s2 has no row, but is still present so callers never fall through
        # to a per-staff query.
        assert result == {"s1": 5, "s2": 1}
        assert mock.objects.filter.call_args.kwargs["staff_key__in"] == ["s1", "s2"]
    finally:
        patcher.stop()


def test_prefetch_limits_uses_one_query_for_deduped_keys():
    patcher, mock = _configured([])
    try:
        prefetch_concurrent_limits(["s1", "s1", "s2", ""])

        assert mock.objects.filter.call_count == 1
        assert mock.objects.filter.call_args.kwargs["staff_key__in"] == ["s1", "s2"]
    finally:
        patcher.stop()


def test_prefetch_limits_falls_back_for_non_positive_values():
    patcher, _ = _configured([("s1", 0), ("s2", None)])
    try:
        assert prefetch_concurrent_limits(["s1", "s2"], default=3) == {"s1": 3, "s2": 3}
    finally:
        patcher.stop()


def test_prefetch_limits_no_keys_skips_the_query():
    patcher, mock = _configured([])
    try:
        assert prefetch_concurrent_limits([]) == {}
        assert prefetch_concurrent_limits(["", None]) == {}
        mock.objects.filter.assert_not_called()
    finally:
        patcher.stop()


# prefetch_blocking_appointments ----------------------------------------

def _appointments(rows):
    patcher = patch(f"{LOGIC}.Appointment")
    mock = patcher.start()
    mock.objects.filter.return_value.exclude.return_value.values_list.return_value = rows
    return patcher, mock


def test_prefetch_appointments_groups_by_staff_and_converts_to_local():
    rows = [
        ("s1", datetime.datetime(2026, 5, 7, 18, 0, tzinfo=UTC), 30),
        ("s2", datetime.datetime(2026, 5, 7, 19, 0, tzinfo=UTC), 60),
    ]
    patcher, mock = _appointments(rows)
    try:
        result = prefetch_blocking_appointments(
            ["s1", "s2"],
            datetime.datetime(2026, 5, 1),
            datetime.datetime(2026, 6, 1),
            "America/New_York",
        )

        # 18:00 UTC is 14:00 EDT; end derived from duration_minutes.
        assert result["s1"] == [
            (datetime.datetime(2026, 5, 7, 14, 0), datetime.datetime(2026, 5, 7, 14, 30))
        ]
        assert result["s2"] == [
            (datetime.datetime(2026, 5, 7, 15, 0), datetime.datetime(2026, 5, 7, 16, 0))
        ]
        assert mock.objects.filter.call_count == 1
    finally:
        patcher.stop()


def test_prefetch_appointments_includes_staff_with_no_appointments():
    patcher, _ = _appointments([])
    try:
        result = prefetch_blocking_appointments(
            ["s1"], datetime.datetime(2026, 5, 1), datetime.datetime(2026, 6, 1)
        )

        assert result == {"s1": []}
    finally:
        patcher.stop()


def test_prefetch_appointments_widens_the_window_for_utc_offset():
    patcher, mock = _appointments([])
    try:
        prefetch_blocking_appointments(
            ["s1"], datetime.datetime(2026, 5, 1), datetime.datetime(2026, 6, 1)
        )

        kwargs = mock.objects.filter.call_args.kwargs
        assert kwargs["start_time__gte"] == datetime.datetime(2026, 4, 30, 8, 0)
        assert kwargs["start_time__lt"] == datetime.datetime(2026, 6, 1, 16, 0)
    finally:
        patcher.stop()


def test_prefetch_appointments_skips_rows_missing_start_or_duration():
    rows = [
        ("s1", None, 30),
        ("s1", datetime.datetime(2026, 5, 7, 18, 0, tzinfo=UTC), None),
    ]
    patcher, _ = _appointments(rows)
    try:
        result = prefetch_blocking_appointments(
            ["s1"], datetime.datetime(2026, 5, 1), datetime.datetime(2026, 6, 1)
        )

        assert result == {"s1": []}
    finally:
        patcher.stop()


def test_prefetch_appointments_no_ids_skips_the_query():
    patcher, mock = _appointments([])
    try:
        assert prefetch_blocking_appointments([], datetime.datetime(2026, 5, 1), datetime.datetime(2026, 6, 1)) == {}
        mock.objects.filter.assert_not_called()
    finally:
        patcher.stop()


# _get_blocking_appointments with a cache -------------------------------

def test_cached_lookup_filters_to_the_day_without_querying():
    cache = {
        "s1": [
            # Previous day — outside the window.
            (datetime.datetime(2026, 5, 6, 9, 0), datetime.datetime(2026, 5, 6, 9, 30)),
            # Overlaps the window.
            (datetime.datetime(2026, 5, 7, 9, 0), datetime.datetime(2026, 5, 7, 9, 30)),
        ]
    }
    patcher, mock = _appointments([])
    try:
        result = _get_blocking_appointments(
            "s1",
            datetime.datetime(2026, 5, 7, 8, 0),
            datetime.datetime(2026, 5, 7, 17, 0),
            "America/New_York",
            booked_cache=cache,
        )

        assert result == [
            (datetime.datetime(2026, 5, 7, 9, 0), datetime.datetime(2026, 5, 7, 9, 30))
        ]
        mock.objects.filter.assert_not_called()
    finally:
        patcher.stop()


# Query-count regression -------------------------------------------------

def test_month_sweep_issues_one_query_per_table_regardless_of_providers():
    """Guards the N+1 fix.

    The month view used to run one Appointment query and one StaffSlotConfig
    query per provider per day — 11 providers × 31 days was ~682 queries.
    Both are now prefetched once for the whole month.
    """
    providers = [{"id": f"p{i}", "name": f"Provider {i}"} for i in range(11)]
    window = [
        (datetime.datetime(2026, 5, 1, 9, 0), datetime.datetime(2026, 5, 1, 17, 0))
    ]
    appt_patcher, appt_mock = _appointments([])
    cfg_patcher, cfg_mock = _configured([])
    try:
        with patch(f"{LOGIC}.get_availability_windows", return_value=window), patch(
            f"{LOGIC}.get_blocking_calendar_events", return_value=[]
        ), patch(f"{LOGIC}.resolve_room_staff", return_value=[]):
            counts = build_month_slot_counts(providers, 2026, 5, 30)

        assert len(counts) == 31
        assert appt_mock.objects.filter.call_count == 1
        assert cfg_mock.objects.filter.call_count == 1
    finally:
        appt_patcher.stop()
        cfg_patcher.stop()


def test_cached_lookup_for_unknown_staff_returns_empty():
    patcher, mock = _appointments([])
    try:
        result = _get_blocking_appointments(
            "missing",
            datetime.datetime(2026, 5, 7, 8, 0),
            datetime.datetime(2026, 5, 7, 17, 0),
            booked_cache={"s1": []},
        )

        assert result == []
        mock.objects.filter.assert_not_called()
    finally:
        patcher.stop()
