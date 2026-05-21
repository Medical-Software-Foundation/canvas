"""Tests for provider_availability.engine.models."""

import datetime as dt
import json
from datetime import date, datetime, timedelta
from unittest.mock import call

from provider_availability.engine.models import (
    AdminBlock,
    AvailableSlot,
    BookingInterval,
    BufferTime,
    DateOverride,
    DAYS_OF_WEEK,
    ProviderAvailabilityRule,
    RecurringBlock,
    TimeWindow,
    date_in_pattern,
    recurrence_anchor,
)


# ── TimeWindow ────────────────────────────────────────────────────────


class TestTimeWindow:
    def test_duration_minutes(self):
        tw = TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))
        assert tw.duration_minutes() == 180

    def test_duration_minutes_short(self):
        tw = TimeWindow(start=dt.time(9, 0), end=dt.time(9, 30))
        assert tw.duration_minutes() == 30

    def test_overlaps_true(self):
        a = TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))
        b = TimeWindow(start=dt.time(11, 0), end=dt.time(14, 0))
        assert a.overlaps(b) is True

    def test_overlaps_false(self):
        a = TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))
        b = TimeWindow(start=dt.time(13, 0), end=dt.time(14, 0))
        assert a.overlaps(b) is False

    def test_overlaps_adjacent_is_false(self):
        a = TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))
        b = TimeWindow(start=dt.time(12, 0), end=dt.time(14, 0))
        assert a.overlaps(b) is False

    def test_to_dict(self):
        tw = TimeWindow(start=dt.time(9, 0), end=dt.time(17, 30))
        result = tw.to_dict()
        assert result == {"start": "09:00", "end": "17:30"}

    def test_from_dict(self):
        tw = TimeWindow.from_dict({"start": "09:00", "end": "17:30"})
        assert tw.start == dt.time(9, 0)
        assert tw.end == dt.time(17, 30)

    def test_roundtrip(self):
        original = TimeWindow(start=dt.time(8, 15), end=dt.time(16, 45))
        restored = TimeWindow.from_dict(original.to_dict())
        assert restored.start == original.start
        assert restored.end == original.end


# ── BufferTime ────────────────────────────────────────────────────────


class TestBufferTime:
    def test_defaults(self):
        bt = BufferTime()
        assert bt.pre == 0
        assert bt.post == 15

    def test_to_dict(self):
        bt = BufferTime(pre=5, post=10)
        assert bt.to_dict() == {"pre": 5, "post": 10}

    def test_from_dict(self):
        bt = BufferTime.from_dict({"pre": 5, "post": 10})
        assert bt.pre == 5
        assert bt.post == 10

    def test_from_dict_defaults(self):
        bt = BufferTime.from_dict({})
        assert bt.pre == 0
        assert bt.post == 15

    def test_roundtrip(self):
        original = BufferTime(pre=10, post=20)
        restored = BufferTime.from_dict(original.to_dict())
        assert restored.pre == original.pre
        assert restored.post == original.post


# ── BookingInterval ───────────────────────────────────────────────────


class TestBookingInterval:
    def test_defaults(self):
        bi = BookingInterval()
        assert bi.min_lead_hours == 24
        assert bi.slot_granularity_minutes == 15

    def test_to_dict(self):
        bi = BookingInterval(min_lead_hours=48, slot_granularity_minutes=30)
        assert bi.to_dict() == {"min_lead_hours": 48, "slot_granularity_minutes": 30}

    def test_from_dict(self):
        bi = BookingInterval.from_dict({"min_lead_hours": 48, "slot_granularity_minutes": 30})
        assert bi.min_lead_hours == 48
        assert bi.slot_granularity_minutes == 30

    def test_from_dict_defaults(self):
        bi = BookingInterval.from_dict({})
        assert bi.min_lead_hours == 24
        assert bi.slot_granularity_minutes == 15


# ── DateOverride ──────────────────────────────────────────────────────


class TestDateOverride:
    def test_closed_day(self):
        do = DateOverride(date=date(2026, 12, 25), is_closed=True)
        d = do.to_dict()
        assert d["date"] == "2026-12-25"
        assert d["is_closed"] is True
        assert d["time_windows"] == []

    def test_with_time_windows(self):
        do = DateOverride(
            date=date(2026, 3, 15),
            is_closed=False,
            time_windows=[TimeWindow(start=dt.time(10, 0), end=dt.time(14, 0))],
        )
        d = do.to_dict()
        assert len(d["time_windows"]) == 1
        assert d["time_windows"][0] == {"start": "10:00", "end": "14:00"}

    def test_from_dict_closed(self):
        do = DateOverride.from_dict({"date": "2026-12-25", "is_closed": True})
        assert do.date == date(2026, 12, 25)
        assert do.is_closed is True
        assert do.time_windows == []

    def test_roundtrip(self):
        original = DateOverride(
            date=date(2026, 7, 4),
            is_closed=False,
            time_windows=[TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
        )
        restored = DateOverride.from_dict(original.to_dict())
        assert restored.date == original.date
        assert restored.is_closed == original.is_closed
        assert len(restored.time_windows) == 1
        assert restored.time_windows[0].start == dt.time(9, 0)


# ── AdminBlock ────────────────────────────────────────────────────────


class TestAdminBlock:
    def test_cache_key(self, sample_block):
        assert sample_block.cache_key == "pa:blocks:provider-uuid-123:block-uuid-001"

    def test_to_dict(self, sample_block):
        d = sample_block.to_dict()
        assert d["id"] == "block-uuid-001"
        assert d["provider_id"] == "provider-uuid-123"
        assert d["start"] == "2026-03-10T09:00:00"
        assert d["end"] == "2026-03-10T12:00:00"
        assert d["reason"] == "PTO"
        assert d["effective_start"] is None
        assert d["effective_end"] is None
        assert d["group_id"] is None

    def test_to_dict_with_effective_dates(self):
        block = AdminBlock(
            provider_id="p1",
            start=datetime(2026, 3, 10, 9, 0),
            end=datetime(2026, 3, 10, 12, 0),
            effective_start=date(2026, 3, 1),
            effective_end=date(2026, 3, 31),
        )
        d = block.to_dict()
        assert d["effective_start"] == "2026-03-01"
        assert d["effective_end"] == "2026-03-31"

    def test_from_dict_minimal(self):
        block = AdminBlock.from_dict({
            "provider_id": "p1",
            "start": "2026-03-10T09:00:00",
            "end": "2026-03-10T12:00:00",
        })
        assert block.provider_id == "p1"
        assert block.start == datetime(2026, 3, 10, 9, 0)
        assert block.end == datetime(2026, 3, 10, 12, 0)
        assert block.reason == ""
        assert block.effective_start is None

    def test_from_dict_with_effective_dates(self):
        block = AdminBlock.from_dict({
            "provider_id": "p1",
            "start": "2026-03-10T09:00:00",
            "end": "2026-03-10T12:00:00",
            "effective_start": "2026-03-01",
            "effective_end": "2026-03-31",
        })
        assert block.effective_start == date(2026, 3, 1)
        assert block.effective_end == date(2026, 3, 31)

    def test_roundtrip(self, sample_block):
        restored = AdminBlock.from_dict(sample_block.to_dict())
        assert restored.id == sample_block.id
        assert restored.provider_id == sample_block.provider_id
        assert restored.start == sample_block.start
        assert restored.end == sample_block.end
        assert restored.reason == sample_block.reason


# ── RecurringBlock ────────────────────────────────────────────────────


class TestRecurringBlock:
    def test_cache_key(self, sample_recurring_block):
        assert sample_recurring_block.cache_key == "pa:recurring_blocks:provider-uuid-123:recurring-block-001"

    def test_to_dict(self, sample_recurring_block):
        d = sample_recurring_block.to_dict()
        assert d["id"] == "recurring-block-001"
        assert d["provider_id"] == "provider-uuid-123"
        assert d["reason"] == "Lunch"
        assert d["is_active"] is True
        assert d["hold_type"] == "none"
        assert "friday" in d["weekly_schedule"]
        assert d["weekly_schedule"]["friday"] == [{"start": "12:00", "end": "13:00"}]

    def test_from_dict(self):
        rb = RecurringBlock.from_dict({
            "provider_id": "p1",
            "weekly_schedule": {
                "monday": [{"start": "12:00", "end": "13:00"}],
            },
            "reason": "Lunch",
            "hold_type": "same_day",
        })
        assert rb.provider_id == "p1"
        assert rb.hold_type == "same_day"
        assert len(rb.weekly_schedule["monday"]) == 1

    def test_from_dict_with_effective_dates(self):
        rb = RecurringBlock.from_dict({
            "provider_id": "p1",
            "weekly_schedule": {},
            "effective_start": "2026-01-01",
            "effective_end": "2026-12-31",
        })
        assert rb.effective_start == date(2026, 1, 1)
        assert rb.effective_end == date(2026, 12, 31)

    def test_roundtrip(self, sample_recurring_block):
        restored = RecurringBlock.from_dict(sample_recurring_block.to_dict())
        assert restored.id == sample_recurring_block.id
        assert restored.provider_id == sample_recurring_block.provider_id
        assert restored.reason == sample_recurring_block.reason
        assert restored.hold_type == sample_recurring_block.hold_type
        friday_windows = restored.weekly_schedule["friday"]
        assert len(friday_windows) == 1
        assert friday_windows[0].start == dt.time(12, 0)


# ── ProviderAvailabilityRule ──────────────────────────────────────────


class TestProviderAvailabilityRule:
    def test_cache_key(self, sample_rule):
        assert sample_rule.cache_key == "pa:rules:provider-uuid-123:rule-uuid-001"

    def test_to_dict_structure(self, sample_rule):
        d = sample_rule.to_dict()
        assert d["provider_id"] == "provider-uuid-123"
        assert d["location_ids"] == ["location-uuid-456"]
        assert d["visit_types"] == ["visit-type-uuid-789"]
        assert d["is_active"] is True
        assert "monday" in d["weekly_schedule"]
        assert d["buffer_minutes"] == {"pre": 0, "post": 15}
        assert d["booking_interval"] == {"min_lead_hours": 24, "slot_granularity_minutes": 15}

    def test_to_json(self, sample_rule):
        json_str = sample_rule.to_json()
        parsed = json.loads(json_str)
        assert parsed["provider_id"] == "provider-uuid-123"

    def test_from_json(self, sample_rule):
        json_str = sample_rule.to_json()
        restored = ProviderAvailabilityRule.from_json(json_str)
        assert restored.provider_id == sample_rule.provider_id
        assert restored.id == sample_rule.id

    def test_from_dict_backward_compat_location_id(self):
        """location_id (singular) should convert to location_ids (list)."""
        rule = ProviderAvailabilityRule.from_dict({
            "provider_id": "p1",
            "location_id": "loc-1",
        })
        assert rule.location_ids == ["loc-1"]

    def test_from_dict_backward_compat_empty_location_id(self):
        """Empty location_id should produce empty list."""
        rule = ProviderAvailabilityRule.from_dict({
            "provider_id": "p1",
            "location_id": "",
        })
        assert rule.location_ids == []

    def test_from_dict_backward_compat_visit_type(self):
        """visit_type (singular) should convert to visit_types (list)."""
        rule = ProviderAvailabilityRule.from_dict({
            "provider_id": "p1",
            "visit_type": "vt-1",
        })
        assert rule.visit_types == ["vt-1"]

    def test_from_dict_backward_compat_empty_visit_type(self):
        """Empty visit_type should produce empty list."""
        rule = ProviderAvailabilityRule.from_dict({
            "provider_id": "p1",
            "visit_type": "",
        })
        assert rule.visit_types == []

    def test_from_dict_location_ids_takes_precedence(self):
        """When both location_ids and location_id exist, location_ids wins."""
        rule = ProviderAvailabilityRule.from_dict({
            "provider_id": "p1",
            "location_ids": ["loc-a", "loc-b"],
            "location_id": "loc-old",
        })
        assert rule.location_ids == ["loc-a", "loc-b"]

    def test_from_dict_with_effective_dates(self):
        rule = ProviderAvailabilityRule.from_dict({
            "provider_id": "p1",
            "effective_start": "2026-03-01",
            "effective_end": "2026-06-30",
        })
        assert rule.effective_start == date(2026, 3, 1)
        assert rule.effective_end == date(2026, 6, 30)

    def test_from_dict_none_effective_dates(self):
        rule = ProviderAvailabilityRule.from_dict({
            "provider_id": "p1",
            "effective_start": None,
            "effective_end": None,
        })
        assert rule.effective_start is None
        assert rule.effective_end is None

    def test_roundtrip(self, sample_rule):
        restored = ProviderAvailabilityRule.from_dict(sample_rule.to_dict())
        assert restored.provider_id == sample_rule.provider_id
        assert restored.location_ids == sample_rule.location_ids
        assert restored.visit_types == sample_rule.visit_types
        assert restored.is_active == sample_rule.is_active
        assert list(restored.weekly_schedule.keys()) == list(sample_rule.weekly_schedule.keys())


# ── AvailableSlot ─────────────────────────────────────────────────────


class TestAvailableSlot:
    def test_duration_minutes(self):
        slot = AvailableSlot(
            start=datetime(2026, 3, 10, 9, 0),
            end=datetime(2026, 3, 10, 9, 15),
            provider_id="p1",
        )
        assert slot.duration_minutes() == 15

    def test_to_dict(self):
        slot = AvailableSlot(
            start=datetime(2026, 3, 10, 9, 0),
            end=datetime(2026, 3, 10, 9, 30),
            provider_id="p1",
            location_id="loc-1",
            visit_type="vt-1",
        )
        d = slot.to_dict()
        assert d["start"] == "2026-03-10T09:00:00"
        assert d["end"] == "2026-03-10T09:30:00"
        assert d["provider_id"] == "p1"
        assert d["location_id"] == "loc-1"
        assert d["visit_type"] == "vt-1"
        assert d["duration_minutes"] == "30"


# ── DAYS_OF_WEEK ──────────────────────────────────────────────────────


class TestDaysOfWeek:
    def test_correct_order(self):
        assert DAYS_OF_WEEK == (
            "monday", "tuesday", "wednesday", "thursday",
            "friday", "saturday", "sunday",
        )

    def test_length(self):
        assert len(DAYS_OF_WEEK) == 7


# ── New-field defaults & roundtrip ────────────────────────────────────


class TestRecurrenceFieldDefaults:
    def test_rule_defaults(self):
        r = ProviderAvailabilityRule(provider_id="p")
        assert r.recurrence_frequency == "weekly"
        assert r.recurrence_interval == 1
        assert r.time_windows == []

    def test_recurring_block_defaults(self):
        rb = RecurringBlock(provider_id="p")
        assert rb.recurrence_frequency == "weekly"
        assert rb.recurrence_interval == 1
        assert rb.time_windows == []

    def test_admin_block_all_day_default(self):
        ab = AdminBlock(provider_id="p", start=datetime(2025, 1, 1, 9), end=datetime(2025, 1, 1, 17))
        assert ab.all_day is False

    def test_legacy_dict_loads_with_defaults(self):
        # Old cache payload: no recurrence fields, no all_day
        rule = ProviderAvailabilityRule.from_dict({"provider_id": "p"})
        assert rule.recurrence_frequency == "weekly"
        assert rule.recurrence_interval == 1
        block = AdminBlock.from_dict(
            {"provider_id": "p", "start": "2025-01-01T09:00:00", "end": "2025-01-01T17:00:00"}
        )
        assert block.all_day is False

    def test_admin_block_all_day_roundtrip(self):
        ab = AdminBlock(
            provider_id="p",
            start=datetime(2025, 1, 1, 0, 0),
            end=datetime(2025, 1, 2, 0, 0),
            all_day=True,
        )
        assert AdminBlock.from_dict(ab.to_dict()) == ab

    def test_rule_with_time_windows_roundtrip(self):
        rule = ProviderAvailabilityRule(
            provider_id="p",
            recurrence_frequency="daily",
            recurrence_interval=17,
            time_windows=[TimeWindow(start=dt.time(9, 0), end=dt.time(17, 0))],
        )
        assert ProviderAvailabilityRule.from_dict(rule.to_dict()) == rule


# ── Anchor + pattern math ─────────────────────────────────────────────


class TestRecurrenceAnchor:
    def test_weekly_anchor_from_midweek_start(self):
        # Wed Jan 1 2025; schedule on Mondays → anchor is Mon Jan 6
        sched = {"monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(17, 0))]}
        assert recurrence_anchor(date(2025, 1, 1), "weekly", sched) == date(2025, 1, 6)

    def test_weekly_anchor_when_start_is_selected_weekday(self):
        sched = {"wednesday": [TimeWindow(start=dt.time(9, 0), end=dt.time(17, 0))]}
        # Wed Jan 1 2025 is itself the anchor
        assert recurrence_anchor(date(2025, 1, 1), "weekly", sched) == date(2025, 1, 1)

    def test_daily_anchor_is_effective_start(self):
        assert recurrence_anchor(date(2025, 1, 1), "daily", {}) == date(2025, 1, 1)

    def test_weekly_anchor_no_selected_weekdays(self):
        assert recurrence_anchor(date(2025, 1, 1), "weekly", {}) is None

    def test_no_effective_start(self):
        assert recurrence_anchor(None, "weekly", {"monday": [object()]}) is None


class TestDateInPattern:
    def setup_method(self):
        self.sched_mon = {"monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(17, 0))]}

    def test_weekly_interval_1_default(self):
        assert date_in_pattern(date(2025, 1, 6), date(2025, 1, 1), "weekly", 1, self.sched_mon)

    def test_weekly_skips_non_selected_weekday(self):
        assert not date_in_pattern(date(2025, 1, 7), date(2025, 1, 1), "weekly", 1, self.sched_mon)

    def test_biweekly_pattern(self):
        # anchor Mon Jan 6; bi-weekly Mondays: 1/6, 1/20, 2/3...
        eff = date(2025, 1, 1)
        assert date_in_pattern(date(2025, 1, 6), eff, "weekly", 2, self.sched_mon)
        assert not date_in_pattern(date(2025, 1, 13), eff, "weekly", 2, self.sched_mon)
        assert date_in_pattern(date(2025, 1, 20), eff, "weekly", 2, self.sched_mon)

    def test_daily_every_n_days(self):
        eff = date(2025, 1, 1)
        assert date_in_pattern(date(2025, 1, 1), eff, "daily", 17, {})
        assert date_in_pattern(date(2025, 1, 18), eff, "daily", 17, {})
        assert not date_in_pattern(date(2025, 1, 17), eff, "daily", 17, {})

    def test_invalid_interval_returns_false(self):
        assert not date_in_pattern(date(2025, 1, 6), date(2025, 1, 1), "weekly", 0, self.sched_mon)

    def test_before_effective_start(self):
        assert not date_in_pattern(date(2024, 12, 31), date(2025, 1, 1), "weekly", 1, self.sched_mon)
