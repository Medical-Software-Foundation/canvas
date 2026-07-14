"""Coverage tests for provider_availability.engine.event_sync.

Targets previously-uncovered branches: daily recurrence, hold-type blocks,
effective-date windows, override maps, and hold-cleanup delete paths.

Mirrors the mocking patterns in test_event_sync.py exactly:
- patch(f"{MODULE}.<name>") for SDK models and helpers
- to_utc / localize_naive patched with identity-style side_effects
- date patched so date.today() is deterministic while date(...) construction works
- EventEffect.create() / delete() mocked; assertions on call kwargs
"""

import datetime as dt
from datetime import UTC, date, datetime
from unittest.mock import MagicMock, call, patch
from zoneinfo import ZoneInfo

import pytest

from canvas_sdk.effects.calendar import EventRecurrence

from provider_availability.engine.models import (
    DateOverride,
    ProviderAvailabilityRule,
    RecurringBlock,
    TimeWindow,
)
from provider_availability.engine.event_sync import (
    AVAILABILITY_TITLE,
    HOLD_TITLE_PREFIXES,
    RECURRING_BLOCK_TITLE,
    _block_outside_override,
    _build_hold_block_events,
    _build_rule_events,
    _compute_recurring_segments,
    _get_provider_override_map,
    build_block_event_effects,
    build_delete_block_effects,
    build_delete_recurring_block_effects,
    build_hold_block_refresh_effects,
    build_lead_time_block_effects,
    build_recurring_block_sync_effects,
)
from provider_availability.engine.models import BookingInterval

MODULE = "provider_availability.engine.event_sync"
PROVIDER_ID = "provider-uuid-123"
LOCATION_ID = "location-uuid-456"


# ── _build_rule_events: DAILY path (lines 124-125, 172-216) ───────────


class TestBuildRuleEventsDaily:
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}._get_calendar_id")
    def test_daily_no_time_windows_returns_empty(self, mock_get_cal, mock_tz):
        """Daily rule with no time_windows returns empty (lines 124-125)."""
        rule = ProviderAvailabilityRule(
            id="rule-1",
            provider_id=PROVIDER_ID,
            location_ids=[LOCATION_ID],
            recurrence_frequency="daily",
            time_windows=[],
        )
        result = _build_rule_events(rule)

        assert result == []
        assert mock_get_cal.mock_calls == []

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}._get_calendar_id")
    def test_daily_single_window_creates_daily_recurring_event(
        self, mock_get_cal, mock_tz, mock_localize, mock_to_utc
    ):
        """Daily rule emits one Daily recurring event per time_window (lines 183-198)."""
        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_cal.return_value = ("cal-daily-1", [])

        rule = ProviderAvailabilityRule(
            id="rule-1",
            provider_id=PROVIDER_ID,
            location_ids=[LOCATION_ID],
            recurrence_frequency="daily",
            recurrence_interval=1,
            time_windows=[TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
            effective_end=date(2026, 3, 31),
        )

        with patch(f"{MODULE}.date") as mock_date, \
             patch(f"{MODULE}.EventEffect") as mock_event_effect:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            mock_event_effect.return_value.create.return_value = MagicMock()

            result = _build_rule_events(rule)

            init_call = mock_event_effect.call_args_list[0]
            assert init_call.kwargs["title"] == AVAILABILITY_TITLE
            assert init_call.kwargs["calendar_id"] == "cal-daily-1"
            assert init_call.kwargs["recurrence_frequency"] == EventRecurrence.Daily
            assert init_call.kwargs["recurrence_interval"] == 1
            # anchor is today (2026-03-02), starts_at at 09:00
            assert init_call.kwargs["starts_at"].month == 3
            assert init_call.kwargs["starts_at"].day == 2
            assert init_call.kwargs["starts_at"].hour == 9

        assert len(result) == 1

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}._get_calendar_id")
    def test_daily_anchor_advances_to_pattern(
        self, mock_get_cal, mock_tz, mock_localize, mock_to_utc
    ):
        """Daily interval>1 with past effective_start advances anchor (lines 172-179)."""
        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_cal.return_value = ("cal-daily-1", [])

        # effective_start 2026-02-27, today 2026-03-02, interval 3.
        # offset = (03-02 - 02-27).days = 3; 3 % 3 == 0 so anchor = range_start = today.
        rule = ProviderAvailabilityRule(
            id="rule-1",
            provider_id=PROVIDER_ID,
            location_ids=[LOCATION_ID],
            recurrence_frequency="daily",
            recurrence_interval=3,
            time_windows=[TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
            effective_start=date(2026, 2, 27),
            effective_end=date(2026, 3, 31),
        )

        with patch(f"{MODULE}.date") as mock_date, \
             patch(f"{MODULE}.EventEffect") as mock_event_effect:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            mock_event_effect.return_value.create.return_value = MagicMock()

            result = _build_rule_events(rule)

            init_call = mock_event_effect.call_args_list[0]
            # anchor lands on today (2026-03-02) since offset%interval == 0
            assert init_call.kwargs["starts_at"].day == 2

        assert len(result) == 1

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}._get_calendar_id")
    def test_daily_anchor_offset_not_aligned_advances(
        self, mock_get_cal, mock_tz, mock_localize, mock_to_utc
    ):
        """Daily interval>1 with offset not divisible advances to next in-pattern date (line 177)."""
        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_cal.return_value = ("cal-daily-1", [])

        # effective_start 2026-02-28, today 2026-03-02, interval 5.
        # offset = 2; 2 % 5 != 0 -> anchor = range_start + (5 - 2) = 03-02 + 3 = 03-05
        rule = ProviderAvailabilityRule(
            id="rule-1",
            provider_id=PROVIDER_ID,
            location_ids=[LOCATION_ID],
            recurrence_frequency="daily",
            recurrence_interval=5,
            time_windows=[TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
            effective_start=date(2026, 2, 28),
            effective_end=date(2026, 3, 31),
        )

        with patch(f"{MODULE}.date") as mock_date, \
             patch(f"{MODULE}.EventEffect") as mock_event_effect:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            mock_event_effect.return_value.create.return_value = MagicMock()

            result = _build_rule_events(rule)

            init_call = mock_event_effect.call_args_list[0]
            assert init_call.kwargs["starts_at"].day == 5

        assert len(result) == 1

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}._get_calendar_id")
    def test_daily_anchor_beyond_range_end_skips(
        self, mock_get_cal, mock_tz, mock_localize, mock_to_utc
    ):
        """Daily anchor after range_end skips the location (lines 180-181)."""
        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_cal.return_value = ("cal-daily-1", [])

        rule = ProviderAvailabilityRule(
            id="rule-1",
            provider_id=PROVIDER_ID,
            location_ids=[LOCATION_ID],
            recurrence_frequency="daily",
            recurrence_interval=1,
            time_windows=[TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
            effective_start=date(2026, 4, 1),
            effective_end=date(2026, 3, 15),  # end before start -> anchor > range_end
        )

        with patch(f"{MODULE}.date") as mock_date:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

            result = _build_rule_events(rule)

        # anchor (2026-04-01) > range_end (2026-03-15) -> continue, no events
        assert result == []

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}._get_calendar_id")
    def test_daily_with_date_overrides_emits_oneoff(
        self, mock_get_cal, mock_tz, mock_localize, mock_to_utc
    ):
        """Daily rule honors date_overrides with one-off events (lines 200-215)."""
        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_cal.return_value = ("cal-daily-1", [])

        override_open = DateOverride(
            date=date(2026, 3, 10),
            time_windows=[TimeWindow(start=dt.time(14, 0), end=dt.time(16, 0))],
        )
        override_closed = DateOverride(date=date(2026, 3, 11), is_closed=True)
        override_empty = DateOverride(date=date(2026, 3, 12), time_windows=[])

        rule = ProviderAvailabilityRule(
            id="rule-1",
            provider_id=PROVIDER_ID,
            location_ids=[LOCATION_ID],
            recurrence_frequency="daily",
            recurrence_interval=1,
            time_windows=[TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
            effective_end=date(2026, 3, 31),
            date_overrides=[override_open, override_closed, override_empty],
        )

        with patch(f"{MODULE}.date") as mock_date, \
             patch(f"{MODULE}.EventEffect") as mock_event_effect:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            mock_event_effect.return_value.create.return_value = MagicMock()

            result = _build_rule_events(rule)

        # 1 daily recurring event + 1 one-off (only the open override) = 2.
        # closed and empty-window overrides are skipped (line 202).
        assert len(result) == 2
        oneoff_call = mock_event_effect.call_args_list[-1]
        # one-off has no recurrence_frequency kwarg
        assert "recurrence_frequency" not in oneoff_call.kwargs
        assert oneoff_call.kwargs["starts_at"].day == 10
        assert oneoff_call.kwargs["starts_at"].hour == 14


# ── _compute_recurring_segments: off-pattern override (line 333) ──────


class TestComputeRecurringSegmentsOffPattern:
    def test_override_before_first_date_ignored(self):
        """Override before first_date is skipped (line 332-333)."""
        segments = _compute_recurring_segments(
            date(2026, 3, 5), date(2026, 4, 30),
            [date(2026, 2, 26)],  # before first_date
        )
        assert segments == [(date(2026, 3, 5), date(2026, 4, 30))]

    def test_override_not_on_step_pattern_ignored(self):
        """Override that isn't on the step_days pattern is skipped (line 333)."""
        # first_date 2026-03-05 (Thu), step 7. 2026-03-08 is +3 days, not on pattern.
        segments = _compute_recurring_segments(
            date(2026, 3, 5), date(2026, 4, 30),
            [date(2026, 3, 8)],
            step_days=7,
        )
        # Off-pattern override ignored -> single full-range segment
        assert segments == [(date(2026, 3, 5), date(2026, 4, 30))]


# ── build_block_event_effects: location_ids (line 479) ────────────────


class TestBuildBlockEventEffectsLocations:
    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    def test_per_location_events(
        self, mock_get_admin_cal, mock_tz, mock_localize, mock_to_utc
    ):
        """Block with location_ids creates one event per location (line 479)."""
        from provider_availability.engine.models import AdminBlock

        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_admin_cal.side_effect = [
            ("admin-cal-A", []),
            ("admin-cal-B", []),
        ]

        block = AdminBlock(
            id="block-1",
            provider_id=PROVIDER_ID,
            start=datetime(2026, 3, 10, 9, 0),
            end=datetime(2026, 3, 10, 12, 0),
            reason="Offsite",
            location_ids=["loc-A", "loc-B"],
        )

        with patch(f"{MODULE}.EventEffect") as mock_event_effect:
            mock_event_effect.return_value.create.return_value = MagicMock()
            result = build_block_event_effects(block)

            # one event per calendar with matching calendar_id
            cal_ids = [c.kwargs["calendar_id"] for c in mock_event_effect.call_args_list]
            assert cal_ids == ["admin-cal-A", "admin-cal-B"]
            assert all(c.kwargs["title"] == "Offsite" for c in mock_event_effect.call_args_list)

        assert mock_get_admin_cal.mock_calls == [
            call(PROVIDER_ID, "loc-A"),
            call(PROVIDER_ID, "loc-B"),
        ]
        assert len(result) == 2


# ── build_delete_block_effects: title fallback (lines 541-548) ────────


class TestBuildDeleteBlockEffectsTitleFallback:
    @patch(f"{MODULE}.provider_tz", return_value=ZoneInfo("UTC"))
    @patch(f"{MODULE}.get_admin_calendars")
    @patch(f"{MODULE}.get_event_ids")
    def test_title_fallback_when_time_match_empty(
        self, mock_get_ids, mock_get_admin_cals, mock_tz, sample_block
    ):
        """When no stored IDs and time-range match is empty, fall back to title match (lines 540-548)."""
        mock_get_ids.return_value = []

        mock_cal = MagicMock()
        mock_cal.id = "admin-cal-1"
        mock_get_admin_cals.return_value = [mock_cal]

        mock_evt = MagicMock()
        mock_evt.id = "evt-by-title"

        with patch(f"{MODULE}.EventModel.objects") as mock_event_objects:
            # First filter (time-range) returns nothing, second (title) returns the event
            mock_event_objects.filter.side_effect = [[], [mock_evt]]

            result = build_delete_block_effects(PROVIDER_ID, sample_block)

        # Two filter calls: time-range then title. Queries now use a single
        # bulk calendar__id__in lookup rather than one filter per calendar.
        assert mock_event_objects.filter.call_count == 2
        title_call = mock_event_objects.filter.call_args_list[1]
        assert title_call.kwargs["calendar__id__in"] == ["admin-cal-1"]
        assert title_call.kwargs["title"] == sample_block.reason
        assert title_call.kwargs["is_cancelled"] is False
        assert "starts_at__date" in title_call.kwargs
        assert len(result) == 1

    @patch(f"{MODULE}.provider_tz", return_value=ZoneInfo("UTC"))
    @patch(f"{MODULE}.get_admin_calendars")
    @patch(f"{MODULE}.get_event_ids")
    def test_title_fallback_uses_blocked_when_no_reason(
        self, mock_get_ids, mock_get_admin_cals, mock_tz
    ):
        """Empty-reason block uses 'Blocked' as fallback title (line 527 + 541-548)."""
        from provider_availability.engine.models import AdminBlock

        mock_get_ids.return_value = []
        mock_cal = MagicMock()
        mock_cal.id = "admin-cal-1"
        mock_get_admin_cals.return_value = [mock_cal]

        mock_evt = MagicMock()
        mock_evt.id = "evt-1"

        block = AdminBlock(
            id="block-noreason",
            provider_id=PROVIDER_ID,
            start=datetime(2026, 3, 10, 9, 0),
            end=datetime(2026, 3, 10, 12, 0),
            reason="",
        )

        with patch(f"{MODULE}.EventModel.objects") as mock_event_objects:
            mock_event_objects.filter.side_effect = [[], [mock_evt]]

            result = build_delete_block_effects(PROVIDER_ID, block)

        title_call = mock_event_objects.filter.call_args_list[1]
        assert title_call.kwargs["title"] == "Blocked"
        assert len(result) == 1


# ── build_lead_time_block_effects: override branches (lines 660-663, 671) ──


class TestBuildLeadTimeOverrideBranches:
    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.get_admin_calendars")
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    def test_closed_override_day_skipped(
        self, mock_get_admin_cal, mock_tz, mock_get_admin_cals, mock_to_utc
    ):
        """A closed date override within the lead window is skipped (lines 660-663)."""
        tz = ZoneInfo("US/Eastern")
        mock_tz.return_value = tz
        mock_get_admin_cal.return_value = ("admin-cal-1", [])
        mock_get_admin_cals.return_value = []

        rule = ProviderAvailabilityRule(
            id="rule-1",
            provider_id=PROVIDER_ID,
            booking_interval=BookingInterval(min_lead_hours=4),
            weekly_schedule={
                "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(17, 0))],
            },
            # today (Monday 2026-03-02) is a closed override
            date_overrides=[DateOverride(date=date(2026, 3, 2), is_closed=True)],
        )

        mock_now = datetime(2026, 3, 2, 10, 0, tzinfo=tz)
        with patch(f"{MODULE}.datetime") as mock_datetime:
            mock_datetime.now.return_value = mock_now
            mock_datetime.combine = datetime.combine
            mock_datetime.side_effect = lambda *a, **kw: datetime(*a, **kw)

            result = build_lead_time_block_effects(rule)

        # Closed override on the only in-window day -> no lead blocks
        assert result == []

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.get_admin_calendars")
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    def test_open_override_uses_override_windows(
        self, mock_get_admin_cal, mock_tz, mock_get_admin_cals, mock_to_utc
    ):
        """An open override supplies its own windows for lead-time blocking (line 663)."""
        tz = ZoneInfo("US/Eastern")
        mock_tz.return_value = tz
        mock_get_admin_cal.return_value = ("admin-cal-1", [])
        mock_get_admin_cals.return_value = []

        rule = ProviderAvailabilityRule(
            id="rule-1",
            provider_id=PROVIDER_ID,
            booking_interval=BookingInterval(min_lead_hours=4),
            weekly_schedule={
                "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(11, 0))],
            },
            # today override widens availability to 9-17
            date_overrides=[
                DateOverride(
                    date=date(2026, 3, 2),
                    time_windows=[TimeWindow(start=dt.time(9, 0), end=dt.time(17, 0))],
                )
            ],
        )

        mock_now = datetime(2026, 3, 2, 10, 0, tzinfo=tz)
        with patch(f"{MODULE}.datetime") as mock_datetime, \
             patch(f"{MODULE}.EventEffect") as mock_event_effect:
            mock_datetime.now.return_value = mock_now
            mock_datetime.combine = datetime.combine
            mock_datetime.side_effect = lambda *a, **kw: datetime(*a, **kw)
            mock_event_effect.return_value.create.return_value = MagicMock()

            result = build_lead_time_block_effects(rule)

            # block is intersection of [10:00, 14:00] with override [9,17] = [10,14]
            init_call = mock_event_effect.call_args_list[0]
            assert init_call.kwargs["starts_at"].hour == 10
            assert init_call.kwargs["ends_at"].hour == 14

        assert len(result) == 1

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.get_admin_calendars")
    @patch(f"{MODULE}.date_in_pattern", return_value=True)
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    def test_daily_rule_uses_time_windows(
        self, mock_get_admin_cal, mock_tz, mock_pattern, mock_get_admin_cals, mock_to_utc
    ):
        """A daily rule uses rule.time_windows in the lead-time loop (line 671)."""
        tz = ZoneInfo("US/Eastern")
        mock_tz.return_value = tz
        mock_get_admin_cal.return_value = ("admin-cal-1", [])
        mock_get_admin_cals.return_value = []

        rule = ProviderAvailabilityRule(
            id="rule-1",
            provider_id=PROVIDER_ID,
            booking_interval=BookingInterval(min_lead_hours=4),
            recurrence_frequency="daily",
            time_windows=[TimeWindow(start=dt.time(9, 0), end=dt.time(17, 0))],
        )

        mock_now = datetime(2026, 3, 2, 10, 0, tzinfo=tz)
        with patch(f"{MODULE}.datetime") as mock_datetime, \
             patch(f"{MODULE}.EventEffect") as mock_event_effect:
            mock_datetime.now.return_value = mock_now
            mock_datetime.combine = datetime.combine
            mock_datetime.side_effect = lambda *a, **kw: datetime(*a, **kw)
            mock_event_effect.return_value.create.return_value = MagicMock()

            result = build_lead_time_block_effects(rule)

            init_call = mock_event_effect.call_args_list[0]
            assert init_call.kwargs["title"] == "Lead Time"
            assert init_call.kwargs["starts_at"].hour == 10
            assert init_call.kwargs["ends_at"].hour == 14

        assert len(result) == 1


# ── _get_provider_override_map (lines 754-758) ────────────────────────


class TestGetProviderOverrideMap:
    @patch(f"{MODULE}.get_rules_for_provider")
    def test_maps_open_and_closed_overrides(self, mock_get_rules):
        """Closed overrides map to [], open overrides map to their windows (lines 753-758)."""
        windows = [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))]
        rule = ProviderAvailabilityRule(
            id="rule-1",
            provider_id=PROVIDER_ID,
            date_overrides=[
                DateOverride(date=date(2026, 3, 10), time_windows=windows),
                DateOverride(date=date(2026, 3, 11), is_closed=True),
            ],
        )
        mock_get_rules.return_value = [rule]

        result = _get_provider_override_map(PROVIDER_ID)

        assert mock_get_rules.mock_calls == [call(PROVIDER_ID)]
        assert result[date(2026, 3, 11)] == []  # closed -> empty
        assert result[date(2026, 3, 10)] == windows

    @patch(f"{MODULE}.get_rules_for_provider")
    def test_no_rules_returns_empty_map(self, mock_get_rules):
        mock_get_rules.return_value = []
        assert _get_provider_override_map(PROVIDER_ID) == {}


# ── _block_outside_override (lines 767-774) ───────────────────────────


class TestBlockOutsideOverride:
    def test_empty_override_windows_is_outside(self):
        """No override windows (closed day) means all blocks are outside (line 767-768)."""
        block = [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))]
        assert _block_outside_override(block, []) is True

    def test_overlapping_block_is_inside(self):
        """Block overlapping an override window returns False (line 773)."""
        block = [TimeWindow(start=dt.time(10, 0), end=dt.time(11, 0))]
        override = [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))]
        assert _block_outside_override(block, override) is False

    def test_non_overlapping_block_is_outside(self):
        """Block entirely outside override windows returns True (line 774)."""
        block = [TimeWindow(start=dt.time(13, 0), end=dt.time(14, 0))]
        override = [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))]
        assert _block_outside_override(block, override) is True


# ── build_recurring_block_sync_effects: location_ids, daily, splits ───


class TestBuildRecurringBlockSyncDailyAndLocations:
    @pytest.fixture(autouse=True)
    def _mock_override_map(self):
        with patch(f"{MODULE}.get_rules_for_provider", return_value=[]):
            yield

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    @patch(f"{MODULE}.build_delete_recurring_block_effects")
    def test_per_location_calendars(
        self, mock_delete, mock_get_admin_cal, mock_tz, mock_localize, mock_to_utc
    ):
        """Recurring block with location_ids creates events per location (line 818)."""
        mock_delete.return_value = []
        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_admin_cal.side_effect = [
            ("admin-cal-A", []),
            ("admin-cal-B", []),
        ]

        block = RecurringBlock(
            id="rb-1",
            provider_id=PROVIDER_ID,
            weekly_schedule={
                "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(10, 0))],
            },
            reason="Meeting",
            is_active=True,
            location_ids=["loc-A", "loc-B"],
        )

        with patch(f"{MODULE}.date") as mock_date, \
             patch(f"{MODULE}.EventEffect") as mock_event_effect:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            mock_event_effect.return_value.create.return_value = MagicMock()

            result = build_recurring_block_sync_effects(block)

            cal_ids = [c.kwargs["calendar_id"] for c in mock_event_effect.call_args_list]
            assert cal_ids == ["admin-cal-A", "admin-cal-B"]

        assert mock_get_admin_cal.mock_calls == [
            call(PROVIDER_ID, "loc-A"),
            call(PROVIDER_ID, "loc-B"),
        ]
        # 1 weekly event per location = 2
        assert len(result) == 2

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    @patch(f"{MODULE}.build_delete_recurring_block_effects")
    def test_daily_recurring_block(
        self, mock_delete, mock_get_admin_cal, mock_tz, mock_localize, mock_to_utc
    ):
        """Daily recurring block emits a Daily recurring event (lines 834-859)."""
        mock_delete.return_value = []
        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_admin_cal.return_value = ("admin-cal-1", [])

        block = RecurringBlock(
            id="rb-1",
            provider_id=PROVIDER_ID,
            recurrence_frequency="daily",
            recurrence_interval=1,
            time_windows=[TimeWindow(start=dt.time(12, 0), end=dt.time(13, 0))],
            reason="Lunch",
            is_active=True,
            effective_end=date(2026, 3, 31),
        )

        with patch(f"{MODULE}.date") as mock_date, \
             patch(f"{MODULE}.EventEffect") as mock_event_effect:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            mock_event_effect.return_value.create.return_value = MagicMock()

            result = build_recurring_block_sync_effects(block)

            init_call = mock_event_effect.call_args_list[0]
            assert init_call.kwargs["title"] == "Lunch"
            assert init_call.kwargs["recurrence_frequency"] == EventRecurrence.Daily
            assert init_call.kwargs["starts_at"].hour == 12

        assert len(result) == 1

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    @patch(f"{MODULE}.build_delete_recurring_block_effects")
    def test_daily_anchor_beyond_range_end_skips(
        self, mock_delete, mock_get_admin_cal, mock_tz, mock_localize, mock_to_utc
    ):
        """Daily block anchor past range_end skips (lines 835-843)."""
        mock_delete.return_value = []
        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_admin_cal.return_value = ("admin-cal-1", [])

        block = RecurringBlock(
            id="rb-1",
            provider_id=PROVIDER_ID,
            recurrence_frequency="daily",
            recurrence_interval=1,
            time_windows=[TimeWindow(start=dt.time(12, 0), end=dt.time(13, 0))],
            reason="Lunch",
            is_active=True,
            effective_start=date(2026, 4, 1),
            effective_end=date(2026, 3, 15),
        )

        with patch(f"{MODULE}.date") as mock_date:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

            result = build_recurring_block_sync_effects(block)

        assert result == []

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    @patch(f"{MODULE}.build_delete_recurring_block_effects")
    def test_weekly_first_date_beyond_range_end_skipped(
        self, mock_delete, mock_get_admin_cal, mock_tz, mock_localize, mock_to_utc
    ):
        """Weekly block whose first weekday is past range_end is skipped (line 871)."""
        mock_delete.return_value = []
        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_admin_cal.return_value = ("admin-cal-1", [])

        block = RecurringBlock(
            id="rb-1",
            provider_id=PROVIDER_ID,
            weekly_schedule={
                "friday": [TimeWindow(start=dt.time(9, 0), end=dt.time(10, 0))],
            },
            reason="Meeting",
            is_active=True,
            effective_start=date(2026, 3, 2),  # Monday
            effective_end=date(2026, 3, 5),     # Thursday, before Friday
        )

        with patch(f"{MODULE}.date") as mock_date:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

            result = build_recurring_block_sync_effects(block)

        assert result == []

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    @patch(f"{MODULE}.build_delete_recurring_block_effects")
    def test_weekly_override_splits_into_segments(
        self, mock_delete, mock_get_admin_cal, mock_tz, mock_localize, mock_to_utc
    ):
        """An override where the block falls outside its window splits the recurrence (lines 902-921)."""
        mock_delete.return_value = []
        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_admin_cal.return_value = ("admin-cal-1", [])

        block = RecurringBlock(
            id="rb-1",
            provider_id=PROVIDER_ID,
            weekly_schedule={
                # Thursday block 13:00-14:00
                "thursday": [TimeWindow(start=dt.time(13, 0), end=dt.time(14, 0))],
            },
            reason="Meeting",
            is_active=True,
            effective_end=date(2026, 5, 28),
        )

        # Provider override on Thu 2026-04-09 narrows availability to a morning
        # window (9-11) that does NOT overlap the 13-14 block, so the block is
        # "outside" and that date becomes a skip_date -> segment split.
        override_rule = ProviderAvailabilityRule(
            id="ovr-rule",
            provider_id=PROVIDER_ID,
            date_overrides=[
                DateOverride(
                    date=date(2026, 4, 9),
                    time_windows=[TimeWindow(start=dt.time(9, 0), end=dt.time(11, 0))],
                )
            ],
        )

        with patch(f"{MODULE}.date") as mock_date, \
             patch(f"{MODULE}.get_rules_for_provider", return_value=[override_rule]):
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

            result = build_recurring_block_sync_effects(block)

        # Split into 2 segments (before + after 2026-04-09)
        assert len(result) == 2


# ── _build_hold_block_events (lines 944-1026) ─────────────────────────


class TestBuildHoldBlockEvents:
    @pytest.fixture(autouse=True)
    def _mock_override_map(self):
        with patch(f"{MODULE}.get_rules_for_provider", return_value=[]):
            yield

    @patch(f"{MODULE}.provider_tz")
    def test_hold_type_none_returns_empty(self, mock_tz):
        """hold_type 'none' returns empty (lines 947-948)."""
        block = RecurringBlock(
            id="rb-1",
            provider_id=PROVIDER_ID,
            weekly_schedule={
                "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(10, 0))],
            },
            hold_type="none",
        )
        assert _build_hold_block_events(block) == []

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.date_in_pattern", return_value=True)
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    def test_same_day_hold_blocks_future_dates(
        self, mock_get_admin_cal, mock_tz, mock_pattern, mock_localize, mock_to_utc
    ):
        """same_day hold blocks dates strictly after today (lines 943-944, 1007-1018)."""
        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_admin_cal.return_value = ("admin-cal-1", [])

        block = RecurringBlock(
            id="rb-1",
            provider_id=PROVIDER_ID,
            recurrence_frequency="daily",
            time_windows=[TimeWindow(start=dt.time(9, 0), end=dt.time(10, 0))],
            reason="Hold",
            hold_type="same_day",
            effective_end=date(2026, 3, 5),  # small window: 03-03, 03-04, 03-05
        )

        with patch(f"{MODULE}.date") as mock_date, \
             patch(f"{MODULE}.EventEffect") as mock_event_effect:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            mock_event_effect.return_value.create.return_value = MagicMock()

            result = _build_hold_block_events(block)

            first_call = mock_event_effect.call_args_list[0]
            # same_day blocks dates > today; first blocked date is 2026-03-03
            assert first_call.kwargs["title"] == "Same Day Hold: Hold"
            assert first_call.kwargs["starts_at"].day == 3

        # Dates 03-03, 03-04, 03-05 each get one event = 3
        assert len(result) == 3

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.date_in_pattern", return_value=True)
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    def test_next_day_hold_skips_tomorrow(
        self, mock_get_admin_cal, mock_tz, mock_pattern, mock_localize, mock_to_utc
    ):
        """next_day hold blocks dates after today+1 (lines 945-946)."""
        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_admin_cal.return_value = ("admin-cal-1", [])

        block = RecurringBlock(
            id="rb-1",
            provider_id=PROVIDER_ID,
            recurrence_frequency="daily",
            time_windows=[TimeWindow(start=dt.time(9, 0), end=dt.time(10, 0))],
            reason="",
            hold_type="next_day",
            effective_end=date(2026, 3, 5),  # 03-03 skipped, block 03-04, 03-05
        )

        with patch(f"{MODULE}.date") as mock_date, \
             patch(f"{MODULE}.EventEffect") as mock_event_effect:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            mock_event_effect.return_value.create.return_value = MagicMock()

            result = _build_hold_block_events(block)

            first_call = mock_event_effect.call_args_list[0]
            # next_day blocks dates > today+1; first blocked date is 2026-03-04
            assert first_call.kwargs["title"] == "Next Day Hold"
            assert first_call.kwargs["starts_at"].day == 4

        # 03-04, 03-05 = 2 events
        assert len(result) == 2

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.date_in_pattern", return_value=True)
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    def test_no_admin_calendar_skips_location(
        self, mock_get_admin_cal, mock_tz, mock_pattern, mock_localize, mock_to_utc
    ):
        """No admin calendar for the location skips it (lines 971-973)."""
        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_admin_cal.return_value = ("", [])

        block = RecurringBlock(
            id="rb-1",
            provider_id=PROVIDER_ID,
            recurrence_frequency="daily",
            time_windows=[TimeWindow(start=dt.time(9, 0), end=dt.time(10, 0))],
            hold_type="same_day",
            effective_end=date(2026, 3, 5),
        )

        with patch(f"{MODULE}.date") as mock_date:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

            result = _build_hold_block_events(block)

        assert result == []

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    def test_weekly_hold_uses_weekday_windows(
        self, mock_get_admin_cal, mock_tz, mock_localize, mock_to_utc
    ):
        """Weekly hold looks up windows by weekday name (lines 996-998)."""
        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_admin_cal.return_value = ("admin-cal-1", [])

        block = RecurringBlock(
            id="rb-1",
            provider_id=PROVIDER_ID,
            recurrence_frequency="weekly",
            recurrence_interval=1,
            weekly_schedule={
                # Wednesday only
                "wednesday": [TimeWindow(start=dt.time(9, 0), end=dt.time(10, 0))],
            },
            reason="WedHold",
            hold_type="same_day",
            effective_end=date(2026, 3, 12),  # covers Wed 03-04, 03-11
        )

        with patch(f"{MODULE}.date") as mock_date, \
             patch(f"{MODULE}.EventEffect") as mock_event_effect:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            mock_event_effect.return_value.create.return_value = MagicMock()

            result = _build_hold_block_events(block)

            # Only Wednesdays produce events (in-pattern check + weekday window)
            for c in mock_event_effect.call_args_list:
                assert c.kwargs["starts_at"].weekday() == 2  # Wednesday

        # Wednesdays in [2026-03-03 .. 2026-03-12]: 03-04, 03-11 = 2
        assert len(result) == 2

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.date_in_pattern", return_value=True)
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    def test_override_suppresses_hold_date(
        self, mock_get_admin_cal, mock_tz, mock_pattern, mock_localize, mock_to_utc
    ):
        """A date override where the hold falls outside its window suppresses that date (lines 1000-1005)."""
        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_admin_cal.return_value = ("admin-cal-1", [])

        block = RecurringBlock(
            id="rb-1",
            provider_id=PROVIDER_ID,
            recurrence_frequency="daily",
            # Hold at 13:00-14:00
            time_windows=[TimeWindow(start=dt.time(13, 0), end=dt.time(14, 0))],
            reason="Hold",
            hold_type="same_day",
            effective_end=date(2026, 3, 4),  # only 03-03, 03-04 blocked
        )

        # Override on 2026-03-03 narrows to morning 9-11 (does not overlap 13-14)
        override_rule = ProviderAvailabilityRule(
            id="ovr-rule",
            provider_id=PROVIDER_ID,
            date_overrides=[
                DateOverride(
                    date=date(2026, 3, 3),
                    time_windows=[TimeWindow(start=dt.time(9, 0), end=dt.time(11, 0))],
                )
            ],
        )

        with patch(f"{MODULE}.date") as mock_date, \
             patch(f"{MODULE}.get_rules_for_provider", return_value=[override_rule]), \
             patch(f"{MODULE}.EventEffect") as mock_event_effect:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            mock_event_effect.return_value.create.return_value = MagicMock()

            result = _build_hold_block_events(block)

            # 03-03 suppressed by override; only 03-04 remains
            assert len(mock_event_effect.call_args_list) == 1
            assert mock_event_effect.call_args_list[0].kwargs["starts_at"].day == 4

        assert len(result) == 1


# ── build_recurring_block_sync_effects routes hold to _build_hold_block_events ──


class TestRecurringBlockSyncHoldRoute:
    @patch(f"{MODULE}.get_rules_for_provider", return_value=[])
    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.date_in_pattern", return_value=True)
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    @patch(f"{MODULE}.build_delete_recurring_block_effects")
    def test_hold_type_routes_to_hold_events(
        self, mock_delete, mock_get_admin_cal, mock_tz, mock_pattern,
        mock_localize, mock_to_utc, mock_rules
    ):
        """A hold_type block routes to _build_hold_block_events (lines 797-798)."""
        mock_delete.return_value = []
        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_admin_cal.return_value = ("admin-cal-1", [])

        block = RecurringBlock(
            id="rb-1",
            provider_id=PROVIDER_ID,
            recurrence_frequency="daily",
            time_windows=[TimeWindow(start=dt.time(9, 0), end=dt.time(10, 0))],
            reason="Hold",
            hold_type="same_day",
            is_active=True,
            effective_end=date(2026, 3, 4),
        )

        with patch(f"{MODULE}.date") as mock_date, \
             patch(f"{MODULE}.EventEffect") as mock_event_effect:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            mock_event_effect.return_value.create.return_value = MagicMock()

            result = build_recurring_block_sync_effects(block)

            assert all(
                c.kwargs["title"].startswith("Same Day Hold")
                for c in mock_event_effect.call_args_list
            )

        # Blocks 03-03, 03-04 = 2 hold events
        assert len(result) == 2


# ── build_hold_block_refresh_effects (lines 1035-1049) ────────────────


class TestBuildHoldBlockRefreshEffects:
    @patch(f"{MODULE}.get_rules_for_provider", return_value=[])
    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.date_in_pattern", return_value=True)
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    @patch(f"{MODULE}.get_admin_calendars")
    def test_deletes_existing_then_recreates(
        self, mock_get_admin_cals, mock_get_admin_cal, mock_tz, mock_pattern,
        mock_localize, mock_to_utc, mock_rules
    ):
        """Refresh deletes existing hold events (all prefixes) then recreates (lines 1038-1048)."""
        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_admin_cal.return_value = ("admin-cal-1", [])

        mock_cal = MagicMock()
        mock_cal.id = "admin-cal-1"
        mock_get_admin_cals.return_value = [mock_cal]

        existing_evt = MagicMock()
        existing_evt.id = "old-hold-evt"

        block = RecurringBlock(
            id="rb-1",
            provider_id=PROVIDER_ID,
            recurrence_frequency="daily",
            time_windows=[TimeWindow(start=dt.time(9, 0), end=dt.time(10, 0))],
            reason="Hold",
            hold_type="same_day",
            effective_end=date(2026, 3, 3),  # only 03-03 blocked
        )

        with patch(f"{MODULE}.date") as mock_date, \
             patch(f"{MODULE}.EventModel.objects") as mock_event_objects, \
             patch(f"{MODULE}.EventEffect") as mock_event_effect:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            # First prefix returns one existing event, remaining prefixes empty
            side = [[existing_evt]] + [[] for _ in HOLD_TITLE_PREFIXES[1:]]
            mock_event_objects.filter.side_effect = side
            mock_event_effect.return_value.create.return_value = MagicMock()
            mock_event_effect.return_value.delete.return_value = MagicMock()

            result = build_hold_block_refresh_effects(block)

        # One prefix query per HOLD_TITLE_PREFIXES entry
        assert mock_event_objects.filter.call_count == len(HOLD_TITLE_PREFIXES)
        # 1 delete (existing) + 1 create (03-03) = 2
        assert len(result) == 2


# ── build_delete_recurring_block_effects: hold cleanup (1069-1076, 1093-1099) ──


class TestBuildDeleteRecurringBlockHoldCleanup:
    @patch(f"{MODULE}.get_admin_calendars")
    @patch(f"{MODULE}.get_event_ids")
    def test_stored_ids_plus_hold_cleanup(
        self, mock_get_ids, mock_get_admin_cals
    ):
        """Stored-ID path also cleans up hold events when hold_type != none (lines 1068-1076)."""
        mock_get_ids.return_value = ["stored-1", "stored-2"]

        mock_cal = MagicMock()
        mock_cal.id = "admin-cal-1"
        mock_get_admin_cals.return_value = [mock_cal]

        hold_evt = MagicMock()
        hold_evt.id = "hold-evt-1"

        block = RecurringBlock(
            id="rb-1",
            provider_id=PROVIDER_ID,
            reason="Hold",
            hold_type="same_day",
        )

        with patch(f"{MODULE}.EventModel.objects") as mock_event_objects:
            # One hold event on the first prefix, empty for the rest
            side = [[hold_evt]] + [[] for _ in HOLD_TITLE_PREFIXES[1:]]
            mock_event_objects.filter.side_effect = side

            result = build_delete_recurring_block_effects(PROVIDER_ID, block)

        assert mock_get_ids.mock_calls == [call(block.id)]
        # 2 stored-ID deletes + 1 hold-event delete = 3
        assert len(result) == 3
        assert mock_event_objects.filter.call_count == len(HOLD_TITLE_PREFIXES)

    @patch(f"{MODULE}.get_admin_calendars")
    @patch(f"{MODULE}.get_event_ids")
    def test_title_fallback_plus_hold_cleanup(
        self, mock_get_ids, mock_get_admin_cals
    ):
        """Title-fallback path also cleans up hold events when hold_type != none (lines 1092-1099)."""
        mock_get_ids.return_value = []  # no stored IDs -> title fallback

        mock_cal = MagicMock()
        mock_cal.id = "admin-cal-1"
        mock_get_admin_cals.return_value = [mock_cal]

        title_evt = MagicMock()
        title_evt.id = "title-evt-1"
        hold_evt = MagicMock()
        hold_evt.id = "hold-evt-1"

        block = RecurringBlock(
            id="rb-1",
            provider_id=PROVIDER_ID,
            reason="Hold",
            hold_type="next_day",
        )

        with patch(f"{MODULE}.EventModel.objects") as mock_event_objects:
            # First filter = title__in match, then one hold event on first prefix,
            # empty for remaining prefixes.
            side = [[title_evt], [hold_evt]] + [[] for _ in HOLD_TITLE_PREFIXES[1:]]
            mock_event_objects.filter.side_effect = side

            result = build_delete_recurring_block_effects(PROVIDER_ID, block)

        # title match uses title__in with reason + legacy
        title_call = mock_event_objects.filter.call_args_list[0]
        assert title_call.kwargs["title__in"] == ["Hold", RECURRING_BLOCK_TITLE]
        # 1 title delete + 1 hold delete = 2
        assert len(result) == 2
        # 1 title query + N prefix queries
        assert mock_event_objects.filter.call_count == 1 + len(HOLD_TITLE_PREFIXES)
