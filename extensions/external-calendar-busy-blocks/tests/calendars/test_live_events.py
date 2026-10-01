from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from external_calendar_busy_blocks.calendars import live_events

MODULE = "external_calendar_busy_blocks.calendars.live_events"
NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 8, 30, tzinfo=timezone.utc)


def test_live_busy_events_windowed_filter() -> None:
    with patch(f"{MODULE}.CalendarEvent") as MockEvent:
        base_qs = MockEvent.objects.filter.return_value
        result = live_events.live_busy_events("cal-1", NOW, WINDOW_END)

    _, kwargs = MockEvent.objects.filter.call_args
    assert kwargs == {
        "calendar__id": "cal-1",
        "title": "Busy",
        "is_cancelled": False,
        "ends_at__gt": NOW,
    }
    # A window_end adds the upper bound so the read mirrors the parser's window.
    base_qs.filter.assert_called_once_with(starts_at__lt=WINDOW_END)
    assert result is base_qs.filter.return_value


def test_live_busy_events_without_window_skips_upper_bound() -> None:
    with patch(f"{MODULE}.CalendarEvent") as MockEvent:
        base_qs = MockEvent.objects.filter.return_value
        result = live_events.live_busy_events("cal-1", NOW)

    base_qs.filter.assert_not_called()
    assert result is base_qs


def test_busy_ids_by_time_groups_real_uuids_by_time() -> None:
    s1, e1 = datetime(2026, 6, 2, 9, tzinfo=timezone.utc), datetime(2026, 6, 2, 10, tzinfo=timezone.utc)
    s2, e2 = datetime(2026, 6, 3, 9, tzinfo=timezone.utc), datetime(2026, 6, 3, 10, tzinfo=timezone.utc)
    events = [
        MagicMock(id="u1", starts_at=s1, ends_at=e1),
        MagicMock(id="u2", starts_at=s1, ends_at=e1),  # duplicate slot
        MagicMock(id="u3", starts_at=s2, ends_at=e2),
    ]
    with patch(f"{MODULE}.live_busy_events", return_value=events):
        by_time = live_events.busy_ids_by_time("cal-1", NOW, WINDOW_END)

    assert by_time[(s1, e1)] == ["u1", "u2"]
    assert by_time[(s2, e2)] == ["u3"]


def test_live_busy_counts_tallies_per_calendar() -> None:
    with patch(f"{MODULE}.CalendarEvent") as MockEvent:
        MockEvent.objects.filter.return_value.values_list.return_value = [
            "cal-a",
            "cal-a",
            "cal-b",
        ]
        counts = live_events.live_busy_counts(["cal-a", "cal-b"], NOW)

    assert counts == {"cal-a": 2, "cal-b": 1}
    _, kwargs = MockEvent.objects.filter.call_args
    assert kwargs["calendar__id__in"] == ["cal-a", "cal-b"]
    assert kwargs["title"] == "Busy"
    assert kwargs["is_cancelled"] is False


def test_live_busy_counts_empty_input_makes_no_query() -> None:
    with patch(f"{MODULE}.CalendarEvent") as MockEvent:
        counts = live_events.live_busy_counts([], NOW)

    assert counts == {}
    MockEvent.objects.filter.assert_not_called()
