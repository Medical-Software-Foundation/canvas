"""Tests for scheduling_logic.py."""

import datetime
from unittest.mock import MagicMock, patch

from scheduling_with_rooms.utils.scheduling_logic import (
    SLOT_STEP_MINUTES,
    _count_overlaps,
    _generate_time_slots,
    _generate_time_slots_from_windows,
    _get_blocking_appointments,
    _slot_in_windows,
    _subtract_blocks,
    build_all_provider_slots,
    build_all_room_slots,
    build_month_slot_counts,
    build_plain_slots,
    build_slots_with_resource_availability,
)


# _count_overlaps -------------------------------------------------------

def test_count_overlaps_naive_datetimes():
    s = datetime.datetime(2026, 5, 7, 9, 0)
    e = datetime.datetime(2026, 5, 7, 10, 0)
    booked = [
        (datetime.datetime(2026, 5, 7, 9, 30), datetime.datetime(2026, 5, 7, 10, 30)),
    ]
    assert _count_overlaps(s, e, booked) == 1


def test_count_overlaps_no_overlap():
    s = datetime.datetime(2026, 5, 7, 9, 0)
    e = datetime.datetime(2026, 5, 7, 10, 0)
    booked = [
        (datetime.datetime(2026, 5, 7, 11, 0), datetime.datetime(2026, 5, 7, 12, 0)),
    ]
    assert _count_overlaps(s, e, booked) == 0


def test_count_overlaps_strips_tzinfo():
    tz = datetime.timezone.utc
    s = datetime.datetime(2026, 5, 7, 9, 0)
    e = datetime.datetime(2026, 5, 7, 10, 0)
    booked = [
        (
            datetime.datetime(2026, 5, 7, 9, 30, tzinfo=tz),
            datetime.datetime(2026, 5, 7, 10, 30, tzinfo=tz),
        ),
    ]
    assert _count_overlaps(s, e, booked) == 1


def test_count_overlaps_multiple():
    s = datetime.datetime(2026, 5, 7, 9, 0)
    e = datetime.datetime(2026, 5, 7, 11, 0)
    booked = [
        (datetime.datetime(2026, 5, 7, 9, 30), datetime.datetime(2026, 5, 7, 10, 0)),
        (datetime.datetime(2026, 5, 7, 10, 0), datetime.datetime(2026, 5, 7, 10, 30)),
    ]
    assert _count_overlaps(s, e, booked) == 2


# _generate_time_slots --------------------------------------------------

def test_generate_time_slots_default():
    slots = _generate_time_slots("2026-05-07", 60)
    assert len(slots) == 9  # 8AM-5PM = 9 hours
    assert slots[0][0].hour == 8
    assert slots[-1][1].hour == 17


def test_generate_time_slots_too_long():
    slots = _generate_time_slots("2026-05-07", 600)  # 10 hours
    assert slots == []


# _subtract_blocks ------------------------------------------------------

def test_subtract_blocks_no_overlap():
    windows = [(datetime.datetime(2026, 5, 7, 9, 0), datetime.datetime(2026, 5, 7, 17, 0))]
    blocks = [(datetime.datetime(2026, 5, 8, 9, 0), datetime.datetime(2026, 5, 8, 10, 0))]
    result = _subtract_blocks(windows, blocks)
    assert result == windows


def test_subtract_blocks_carves_middle():
    windows = [(datetime.datetime(2026, 5, 7, 9, 0), datetime.datetime(2026, 5, 7, 17, 0))]
    blocks = [(datetime.datetime(2026, 5, 7, 12, 0), datetime.datetime(2026, 5, 7, 13, 0))]
    result = _subtract_blocks(windows, blocks)
    assert len(result) == 2
    assert result[0] == (
        datetime.datetime(2026, 5, 7, 9, 0),
        datetime.datetime(2026, 5, 7, 12, 0),
    )
    assert result[1] == (
        datetime.datetime(2026, 5, 7, 13, 0),
        datetime.datetime(2026, 5, 7, 17, 0),
    )


def test_subtract_blocks_block_at_start():
    windows = [(datetime.datetime(2026, 5, 7, 9, 0), datetime.datetime(2026, 5, 7, 17, 0))]
    blocks = [(datetime.datetime(2026, 5, 7, 9, 0), datetime.datetime(2026, 5, 7, 10, 0))]
    result = _subtract_blocks(windows, blocks)
    assert result == [
        (datetime.datetime(2026, 5, 7, 10, 0), datetime.datetime(2026, 5, 7, 17, 0)),
    ]


def test_subtract_blocks_block_covers_window():
    windows = [(datetime.datetime(2026, 5, 7, 9, 0), datetime.datetime(2026, 5, 7, 17, 0))]
    blocks = [(datetime.datetime(2026, 5, 7, 8, 0), datetime.datetime(2026, 5, 7, 18, 0))]
    result = _subtract_blocks(windows, blocks)
    assert result == []


# _generate_time_slots_from_windows -------------------------------------

def test_generate_time_slots_from_windows():
    windows = [(datetime.datetime(2026, 5, 7, 9, 0), datetime.datetime(2026, 5, 7, 11, 0))]
    slots = _generate_time_slots_from_windows(windows, 30)
    # 30-min slots, 30-min step → 4 slots (9:00, 9:30, 10:00, 10:30)
    assert len(slots) == 4


def test_generate_time_slots_from_windows_custom_step():
    windows = [(datetime.datetime(2026, 5, 7, 9, 0), datetime.datetime(2026, 5, 7, 12, 0))]
    slots = _generate_time_slots_from_windows(windows, 60, step_minutes=60)
    assert len(slots) == 3


def test_generate_time_slots_from_windows_empty():
    assert _generate_time_slots_from_windows([], 30) == []


# _slot_in_windows ------------------------------------------------------

def test_slot_in_windows_inside():
    windows = [(datetime.datetime(2026, 5, 7, 9, 0), datetime.datetime(2026, 5, 7, 17, 0))]
    s = datetime.datetime(2026, 5, 7, 10, 0)
    e = datetime.datetime(2026, 5, 7, 11, 0)
    assert _slot_in_windows(s, e, windows) is True


def test_slot_in_windows_outside():
    windows = [(datetime.datetime(2026, 5, 7, 9, 0), datetime.datetime(2026, 5, 7, 12, 0))]
    s = datetime.datetime(2026, 5, 7, 13, 0)
    e = datetime.datetime(2026, 5, 7, 14, 0)
    assert _slot_in_windows(s, e, windows) is False


def test_slot_in_windows_partial_overlap():
    windows = [(datetime.datetime(2026, 5, 7, 9, 0), datetime.datetime(2026, 5, 7, 12, 0))]
    s = datetime.datetime(2026, 5, 7, 11, 30)
    e = datetime.datetime(2026, 5, 7, 12, 30)
    assert _slot_in_windows(s, e, windows) is False


# _get_blocking_appointments --------------------------------------------

def test_get_blocking_appointments_includes_only_overlapping():
    appt_start = datetime.datetime(2026, 5, 7, 10, 0, tzinfo=datetime.timezone.utc)
    far_appt_start = datetime.datetime(2026, 5, 8, 10, 0, tzinfo=datetime.timezone.utc)

    with patch(
        "scheduling_with_rooms.utils.scheduling_logic.Appointment"
    ) as mock_appt:
        mock_appt.objects.filter.return_value.exclude.return_value.values_list.return_value = [
            (appt_start, 30, "booked"),
            (far_appt_start, 30, "booked"),  # overlapping window check filters out
            (None, 30, "booked"),  # missing start dropped
        ]
        day_start = datetime.datetime(2026, 5, 7, 8, 0)
        day_end = datetime.datetime(2026, 5, 7, 18, 0)
        result = _get_blocking_appointments("p1", day_start, day_end, "UTC")
        assert len(result) == 1
        assert result[0][0].hour == 10


def test_get_blocking_appointments_no_calendar_tz():
    appt_start = datetime.datetime(2026, 5, 7, 10, 0, tzinfo=datetime.timezone.utc)

    with patch(
        "scheduling_with_rooms.utils.scheduling_logic.Appointment"
    ) as mock_appt:
        mock_appt.objects.filter.return_value.exclude.return_value.values_list.return_value = [
            (appt_start, 30, "booked"),
        ]
        day_start = datetime.datetime(2026, 5, 7, 8, 0)
        day_end = datetime.datetime(2026, 5, 7, 18, 0)
        # No calendar_tz → tz is None branch.
        result = _get_blocking_appointments("p1", day_start, day_end, "")
        assert len(result) == 1


def test_get_blocking_appointments_naive_starts():
    naive_start = datetime.datetime(2026, 5, 7, 10, 0)

    with patch(
        "scheduling_with_rooms.utils.scheduling_logic.Appointment"
    ) as mock_appt:
        mock_appt.objects.filter.return_value.exclude.return_value.values_list.return_value = [
            (naive_start, 30, "booked"),
        ]
        day_start = datetime.datetime(2026, 5, 7, 8, 0)
        day_end = datetime.datetime(2026, 5, 7, 18, 0)
        result = _get_blocking_appointments("p1", day_start, day_end, "")
        assert len(result) == 1


# build_plain_slots -----------------------------------------------------

def test_build_plain_slots_no_windows():
    with patch(
        "scheduling_with_rooms.utils.scheduling_logic.get_availability_windows",
        return_value=[],
    ):
        result = build_plain_slots("p1", "loc", "2026-05-07", 30)
        assert result == []


def test_build_plain_slots_basic():
    win = [(datetime.datetime(2026, 5, 7, 9, 0), datetime.datetime(2026, 5, 7, 11, 0))]
    with patch(
        "scheduling_with_rooms.utils.scheduling_logic.get_availability_windows",
        return_value=win,
    ), patch(
        "scheduling_with_rooms.utils.scheduling_logic._get_blocking_appointments",
        return_value=[],
    ), patch(
        "scheduling_with_rooms.utils.scheduling_logic.get_blocking_calendar_events",
        return_value=[],
    ), patch(
        "scheduling_with_rooms.utils.scheduling_logic.get_concurrent_limit",
        return_value=1,
    ):
        result = build_plain_slots("p1", "loc", "2026-05-07", 30)
        assert len(result) == 4


def test_build_plain_slots_with_hard_block_excludes():
    win = [(datetime.datetime(2026, 5, 7, 9, 0), datetime.datetime(2026, 5, 7, 11, 0))]
    hard = [(datetime.datetime(2026, 5, 7, 9, 0), datetime.datetime(2026, 5, 7, 9, 30))]
    with patch(
        "scheduling_with_rooms.utils.scheduling_logic.get_availability_windows",
        return_value=win,
    ), patch(
        "scheduling_with_rooms.utils.scheduling_logic._get_blocking_appointments",
        return_value=[],
    ), patch(
        "scheduling_with_rooms.utils.scheduling_logic.get_blocking_calendar_events",
        return_value=hard,
    ), patch(
        "scheduling_with_rooms.utils.scheduling_logic.get_concurrent_limit",
        return_value=1,
    ):
        result = build_plain_slots("p1", "loc", "2026-05-07", 30)
        # The 9:00 slot overlaps the hard block, so 3 remain.
        assert len(result) == 3


def test_build_plain_slots_concurrent_limit_two():
    win = [(datetime.datetime(2026, 5, 7, 9, 0), datetime.datetime(2026, 5, 7, 10, 0))]
    booked = [(datetime.datetime(2026, 5, 7, 9, 0), datetime.datetime(2026, 5, 7, 9, 30))]
    with patch(
        "scheduling_with_rooms.utils.scheduling_logic.get_availability_windows",
        return_value=win,
    ), patch(
        "scheduling_with_rooms.utils.scheduling_logic._get_blocking_appointments",
        return_value=booked,
    ), patch(
        "scheduling_with_rooms.utils.scheduling_logic.get_blocking_calendar_events",
        return_value=[],
    ), patch(
        "scheduling_with_rooms.utils.scheduling_logic.get_concurrent_limit",
        return_value=2,
    ):
        result = build_plain_slots("p1", "loc", "2026-05-07", 30)
        # Concurrent limit is 2, only 1 booking → both slots available
        assert len(result) == 2


# build_all_provider_slots ----------------------------------------------

def test_build_all_provider_slots_empty():
    result = build_all_provider_slots([], "loc", "2026-05-07", 30)
    assert result == []


def test_build_all_provider_slots_iterates():
    providers = [{"id": "p1", "name": "Bob"}, {"id": "p2", "name": "Alice"}]
    with patch(
        "scheduling_with_rooms.utils.scheduling_logic.build_plain_slots",
        return_value=[{"start": "x", "end": "y"}],
    ):
        result = build_all_provider_slots(providers, "loc", "2026-05-07", 30)
        assert len(result) == 2
        assert result[0]["id"] == "p1"
        assert result[1]["name"] == "Alice"


# build_month_slot_counts -----------------------------------------------

def test_build_month_slot_counts_no_rooms():
    providers = [{"id": "p1", "name": "Bob"}]
    with patch(
        "scheduling_with_rooms.utils.scheduling_logic.build_plain_slots",
        return_value=[{"start": "x", "end": "y"}],
    ):
        result = build_month_slot_counts(providers, 2026, 5, 30)
        assert len(result) == 31  # May has 31 days
        assert result["2026-05-01"] == 1


def test_build_month_slot_counts_february():
    providers = [{"id": "p1", "name": "Bob"}]
    with patch(
        "scheduling_with_rooms.utils.scheduling_logic.build_plain_slots",
        return_value=[],
    ):
        result = build_month_slot_counts(providers, 2026, 2, 30)
        assert len(result) == 28  # 2026 is not a leap year


def test_build_month_slot_counts_december():
    # Code path: month >= 12 uses 31 days fallback.
    providers = []
    with patch(
        "scheduling_with_rooms.utils.scheduling_logic.build_plain_slots",
        return_value=[],
    ):
        result = build_month_slot_counts(providers, 2026, 12, 30)
        assert len(result) == 31


def test_build_month_slot_counts_with_rooms_intersect():
    providers = [{"id": "p1", "name": "Bob"}]
    rooms_data = [{"id": "r1", "name": "Exam 1", "slots": [{"start": "2026-05-07T09:00"}]}]
    plain_slots = [
        {"start": "2026-05-07T09:00", "end": "2026-05-07T09:30"},
        {"start": "2026-05-07T10:00", "end": "2026-05-07T10:30"},
    ]
    with patch(
        "scheduling_with_rooms.utils.scheduling_logic.build_all_room_slots",
        return_value=rooms_data,
    ), patch(
        "scheduling_with_rooms.utils.scheduling_logic.build_plain_slots",
        return_value=plain_slots,
    ):
        result = build_month_slot_counts(
            providers, 2026, 5, 30, allowed_room_keys={"r1"}
        )
        # 31 days, each day: 1 room start, 2 plain slots, intersect=1
        assert result["2026-05-07"] == 1


# build_all_room_slots --------------------------------------------------

def test_build_all_room_slots_no_staff():
    with patch(
        "scheduling_with_rooms.utils.scheduling_logic.Staff"
    ) as mock_staff:
        mock_staff.objects.filter.return_value.distinct.return_value = []
        result = build_all_room_slots("2026-05-07", 30)
        assert result == []


def test_build_all_room_slots_no_windows_returns_empty_slots():
    rr = MagicMock()
    rr.id = "r1"
    rr.full_name = "Exam 1"

    with patch(
        "scheduling_with_rooms.utils.scheduling_logic.Staff"
    ) as mock_staff, patch(
        "scheduling_with_rooms.utils.scheduling_logic.get_availability_windows",
        return_value=[],
    ):
        mock_staff.objects.filter.return_value.distinct.return_value = MagicMock(
            __iter__=lambda self: iter([rr]), __len__=lambda self: 1
        )
        # `mock_staff.objects.filter.return_value.distinct.return_value` is iterable;
        # but the function calls `list()` on `rr_qs`. Patch differently:
        mock_staff.objects.filter.return_value.distinct.return_value = [rr]
        result = build_all_room_slots("2026-05-07", 30)
        assert len(result) == 1
        assert result[0]["slots"] == []


def test_build_all_room_slots_with_allowed_keys():
    rr = MagicMock()
    rr.id = "r1"
    rr.full_name = "Exam 1"

    win = [(datetime.datetime(2026, 5, 7, 9, 0), datetime.datetime(2026, 5, 7, 11, 0))]

    with patch(
        "scheduling_with_rooms.utils.scheduling_logic.Staff"
    ) as mock_staff, patch(
        "scheduling_with_rooms.utils.scheduling_logic.get_availability_windows",
        return_value=win,
    ), patch(
        "scheduling_with_rooms.utils.scheduling_logic.get_blocking_calendar_events",
        return_value=[],
    ), patch(
        "scheduling_with_rooms.utils.scheduling_logic._get_blocking_appointments",
        return_value=[],
    ), patch(
        "scheduling_with_rooms.utils.scheduling_logic.get_concurrent_limit",
        return_value=1,
    ):
        # `filter().distinct()` then `.filter()` with allowed keys, then iterated.
        chained = MagicMock()
        chained.filter.return_value = [rr]
        mock_staff.objects.filter.return_value.distinct.return_value = chained
        result = build_all_room_slots("2026-05-07", 60, allowed_room_keys={"r1"})
        # 9-11 window with 60-min appt + step=duration → 2 slots (9, 10).
        assert len(result) == 1
        assert len(result[0]["slots"]) == 2


def test_build_all_room_slots_empty_after_subtract():
    rr = MagicMock()
    rr.id = "r1"
    rr.full_name = "Exam 1"

    win = [(datetime.datetime(2026, 5, 7, 9, 0), datetime.datetime(2026, 5, 7, 9, 30))]
    blocks = [(datetime.datetime(2026, 5, 7, 9, 0), datetime.datetime(2026, 5, 7, 9, 30))]

    with patch(
        "scheduling_with_rooms.utils.scheduling_logic.Staff"
    ) as mock_staff, patch(
        "scheduling_with_rooms.utils.scheduling_logic.get_availability_windows",
        return_value=win,
    ), patch(
        "scheduling_with_rooms.utils.scheduling_logic.get_blocking_calendar_events",
        return_value=blocks,
    ):
        mock_staff.objects.filter.return_value.distinct.return_value = [rr]
        result = build_all_room_slots("2026-05-07", 30)
        # Window fully blocked → empty slot list.
        assert result[0]["slots"] == []


# build_slots_with_resource_availability ---------------------------------

def test_build_slots_with_resource_availability_no_provider_windows():
    with patch(
        "scheduling_with_rooms.utils.scheduling_logic.get_availability_windows",
        return_value=[],
    ):
        result = build_slots_with_resource_availability(
            "p1", "loc", "2026-05-07", 30
        )
        assert result == []


def test_build_slots_with_resource_availability_no_rooms():
    win = [(datetime.datetime(2026, 5, 7, 9, 0), datetime.datetime(2026, 5, 7, 11, 0))]
    with patch(
        "scheduling_with_rooms.utils.scheduling_logic.get_availability_windows",
        return_value=win,
    ), patch(
        "scheduling_with_rooms.utils.scheduling_logic._get_blocking_appointments",
        return_value=[],
    ), patch(
        "scheduling_with_rooms.utils.scheduling_logic.get_blocking_calendar_events",
        return_value=[],
    ), patch(
        "scheduling_with_rooms.utils.scheduling_logic.get_concurrent_limit",
        return_value=1,
    ), patch(
        "scheduling_with_rooms.utils.scheduling_logic.Staff"
    ) as mock_staff:
        mock_staff.objects.filter.return_value.distinct.return_value = []
        result = build_slots_with_resource_availability(
            "p1", "loc", "2026-05-07", 30
        )
        assert result == []


def test_build_slots_with_resource_availability_full():
    rr = MagicMock()
    rr.id = "r1"
    rr.full_name = "Exam 1"

    win = [(datetime.datetime(2026, 5, 7, 9, 0), datetime.datetime(2026, 5, 7, 11, 0))]

    with patch(
        "scheduling_with_rooms.utils.scheduling_logic.get_availability_windows",
        return_value=win,
    ), patch(
        "scheduling_with_rooms.utils.scheduling_logic._get_blocking_appointments",
        return_value=[],
    ), patch(
        "scheduling_with_rooms.utils.scheduling_logic.get_blocking_calendar_events",
        return_value=[],
    ), patch(
        "scheduling_with_rooms.utils.scheduling_logic.get_concurrent_limit",
        return_value=1,
    ), patch(
        "scheduling_with_rooms.utils.scheduling_logic.Staff"
    ) as mock_staff:
        chained = MagicMock()
        chained.filter.return_value = [rr]
        mock_staff.objects.filter.return_value.distinct.return_value = chained
        result = build_slots_with_resource_availability(
            "p1", "loc", "2026-05-07", 30, allowed_room_keys={"r1"},
        )
        # All 4 slots eligible; each has rr available
        assert len(result) == 4
        assert result[0]["available_rr_staff"] == [{"id": "r1", "name": "Exam 1"}]


def test_build_slots_with_resource_availability_provider_hard_block_excludes():
    rr = MagicMock()
    rr.id = "r1"
    rr.full_name = "Exam 1"

    win = [(datetime.datetime(2026, 5, 7, 9, 0), datetime.datetime(2026, 5, 7, 10, 0))]
    hard = [(datetime.datetime(2026, 5, 7, 9, 0), datetime.datetime(2026, 5, 7, 10, 0))]

    with patch(
        "scheduling_with_rooms.utils.scheduling_logic.get_availability_windows",
        return_value=win,
    ), patch(
        "scheduling_with_rooms.utils.scheduling_logic._get_blocking_appointments",
        return_value=[],
    ), patch(
        "scheduling_with_rooms.utils.scheduling_logic.get_blocking_calendar_events",
        return_value=hard,
    ), patch(
        "scheduling_with_rooms.utils.scheduling_logic.get_concurrent_limit",
        return_value=1,
    ), patch(
        "scheduling_with_rooms.utils.scheduling_logic.Staff"
    ) as mock_staff:
        chained = MagicMock()
        chained.filter.return_value = [rr]
        mock_staff.objects.filter.return_value.distinct.return_value = chained
        result = build_slots_with_resource_availability(
            "p1", "loc", "2026-05-07", 30, allowed_room_keys={"r1"},
        )
        # Hard block on provider for that slot → excluded
        assert result == []


def test_build_slots_with_resource_availability_provider_capacity_exhausted():
    rr = MagicMock()
    rr.id = "r1"
    rr.full_name = "Exam 1"

    win = [(datetime.datetime(2026, 5, 7, 9, 0), datetime.datetime(2026, 5, 7, 9, 30))]
    booked = [(datetime.datetime(2026, 5, 7, 9, 0), datetime.datetime(2026, 5, 7, 9, 30))]

    with patch(
        "scheduling_with_rooms.utils.scheduling_logic.get_availability_windows",
        return_value=win,
    ), patch(
        "scheduling_with_rooms.utils.scheduling_logic._get_blocking_appointments",
        return_value=booked,
    ), patch(
        "scheduling_with_rooms.utils.scheduling_logic.get_blocking_calendar_events",
        return_value=[],
    ), patch(
        "scheduling_with_rooms.utils.scheduling_logic.get_concurrent_limit",
        return_value=1,
    ), patch(
        "scheduling_with_rooms.utils.scheduling_logic.Staff"
    ) as mock_staff:
        chained = MagicMock()
        chained.filter.return_value = [rr]
        mock_staff.objects.filter.return_value.distinct.return_value = chained
        result = build_slots_with_resource_availability(
            "p1", "loc", "2026-05-07", 30, allowed_room_keys={"r1"},
        )
        # Capacity exhausted on provider.
        assert result == []


def test_build_slots_with_resource_availability_rr_no_window_skipped():
    rr = MagicMock()
    rr.id = "r1"
    rr.full_name = "Exam 1"

    win = [(datetime.datetime(2026, 5, 7, 9, 0), datetime.datetime(2026, 5, 7, 9, 30))]

    call_count = {"v": 0}

    def windows_side_effect(staff_id, *args, **kwargs):
        call_count["v"] += 1
        if call_count["v"] == 1:
            # First call: provider windows
            return win
        # Subsequent calls: RR windows (none)
        return []

    with patch(
        "scheduling_with_rooms.utils.scheduling_logic.get_availability_windows",
        side_effect=windows_side_effect,
    ), patch(
        "scheduling_with_rooms.utils.scheduling_logic._get_blocking_appointments",
        return_value=[],
    ), patch(
        "scheduling_with_rooms.utils.scheduling_logic.get_blocking_calendar_events",
        return_value=[],
    ), patch(
        "scheduling_with_rooms.utils.scheduling_logic.get_concurrent_limit",
        return_value=1,
    ), patch(
        "scheduling_with_rooms.utils.scheduling_logic.Staff"
    ) as mock_staff:
        chained = MagicMock()
        chained.filter.return_value = [rr]
        mock_staff.objects.filter.return_value.distinct.return_value = chained
        result = build_slots_with_resource_availability(
            "p1", "loc", "2026-05-07", 30, allowed_room_keys={"r1"},
        )
        # Provider has slots but no RR has overlapping windows → excluded.
        assert result == []


def test_slot_step_constant():
    assert SLOT_STEP_MINUTES == 30
