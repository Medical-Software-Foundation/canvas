"""Tests for provider_availability.engine.calculator."""

import datetime as dt
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, call, patch

from provider_availability.engine.models import (
    AdminBlock,
    BookingInterval,
    BufferTime,
    DateOverride,
    ProviderAvailabilityRule,
    RecurringBlock,
    TimeWindow,
)
from provider_availability.engine.calculator import (
    _build_blocked_intervals,
    _is_blocked,
    calculate_available_slots,
    get_available_slots_for_provider,
)


CALC_MODULE = "provider_availability.engine.calculator"


def _make_rule(**overrides):
    """Helper to build a rule with sensible defaults."""
    defaults = {
        "id": "rule-1",
        "provider_id": "p1",
        "location_ids": ["loc-1"],
        "visit_types": ["vt-1"],
        "weekly_schedule": {
            "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
        },
        "buffer_minutes": BufferTime(pre=0, post=0),
        "booking_interval": BookingInterval(min_lead_hours=0, slot_granularity_minutes=60),
        "is_active": True,
    }
    defaults.update(overrides)
    return ProviderAvailabilityRule(**defaults)  # type: ignore[arg-type]


def _standard_patches(**kwargs):
    """Return a dict of standard patches for calculator dependencies."""
    defaults = {
        f"{CALC_MODULE}.Appointment.objects.filter": MagicMock(return_value=MagicMock(values_list=MagicMock(return_value=[]))),
        f"{CALC_MODULE}.get_provider_display": MagicMock(return_value={"name": "", "npi_number": ""}),
        f"{CALC_MODULE}.Event.objects.filter": MagicMock(return_value=MagicMock(exclude=MagicMock(return_value=[]))),
        f"{CALC_MODULE}.get_blocks_for_provider": MagicMock(return_value=[]),
        f"{CALC_MODULE}.get_recurring_blocks_for_provider": MagicMock(return_value=[]),
    }
    defaults.update(kwargs)
    return defaults


# ── _build_blocked_intervals ──────────────────────────────────────────


class TestBuildBlockedIntervals:
    def test_no_appointments(self):
        assert _build_blocked_intervals([], 0, 0) == []

    def test_with_buffers(self):
        appointments = [(datetime(2026, 3, 10, 10, 0), 30)]
        result = _build_blocked_intervals(appointments, pre_buffer=15, post_buffer=15)
        assert len(result) == 1
        assert result[0] == (datetime(2026, 3, 10, 9, 45), datetime(2026, 3, 10, 10, 45))

    def test_no_buffers(self):
        appointments = [(datetime(2026, 3, 10, 10, 0), 30)]
        result = _build_blocked_intervals(appointments, pre_buffer=0, post_buffer=0)
        assert len(result) == 1
        assert result[0] == (datetime(2026, 3, 10, 10, 0), datetime(2026, 3, 10, 10, 30))

    def test_multiple_appointments(self):
        appointments = [
            (datetime(2026, 3, 10, 9, 0), 30),
            (datetime(2026, 3, 10, 14, 0), 60),
        ]
        result = _build_blocked_intervals(appointments, pre_buffer=0, post_buffer=15)
        assert len(result) == 2


# ── _is_blocked ───────────────────────────────────────────────────────


class TestIsBlocked:
    def test_not_blocked(self):
        blocked = [(datetime(2026, 3, 10, 10, 0), datetime(2026, 3, 10, 11, 0))]
        assert _is_blocked(
            datetime(2026, 3, 10, 11, 0), datetime(2026, 3, 10, 12, 0), blocked
        ) is False

    def test_is_blocked(self):
        blocked = [(datetime(2026, 3, 10, 10, 0), datetime(2026, 3, 10, 11, 0))]
        assert _is_blocked(
            datetime(2026, 3, 10, 10, 30), datetime(2026, 3, 10, 11, 30), blocked
        ) is True

    def test_empty_blocked_list(self):
        assert _is_blocked(
            datetime(2026, 3, 10, 9, 0), datetime(2026, 3, 10, 10, 0), []
        ) is False

    def test_adjacent_not_blocked(self):
        blocked = [(datetime(2026, 3, 10, 9, 0), datetime(2026, 3, 10, 10, 0))]
        assert _is_blocked(
            datetime(2026, 3, 10, 10, 0), datetime(2026, 3, 10, 11, 0), blocked
        ) is False


# ── calculate_available_slots ─────────────────────────────────────────


class TestCalculateAvailableSlots:
    def test_inactive_rule_returns_empty(self):
        rule = _make_rule(is_active=False)
        result = calculate_available_slots(
            rule, date(2026, 3, 9), date(2026, 3, 15),
            now=datetime(2026, 3, 1, 0, 0),
        )
        assert result == []

    def test_basic_slot_generation(self):
        """Monday 9:00-12:00 with 60-min granularity should yield 3 slots."""
        rule = _make_rule()

        with patch(f"{CALC_MODULE}.Appointment.objects") as mock_appt, \
             patch(f"{CALC_MODULE}.get_provider_display", return_value={"name": ""}), \
             patch(f"{CALC_MODULE}.Event.objects") as mock_evt, \
             patch(f"{CALC_MODULE}.get_blocks_for_provider", return_value=[]), \
             patch(f"{CALC_MODULE}.get_recurring_blocks_for_provider", return_value=[]):
            mock_appt.filter.return_value.values_list.return_value = []
            mock_evt.filter.return_value.exclude.return_value = []

            # Monday is 2026-03-09
            slots = calculate_available_slots(
                rule, date(2026, 3, 9), date(2026, 3, 9),
                now=datetime(2026, 3, 1, 0, 0),
            )

            assert len(slots) == 3
            assert slots[0].start == datetime(2026, 3, 9, 9, 0)
            assert slots[0].end == datetime(2026, 3, 9, 10, 0)
            assert slots[1].start == datetime(2026, 3, 9, 10, 0)
            assert slots[2].start == datetime(2026, 3, 9, 11, 0)

    def test_lead_time_enforcement(self):
        """Slots before now + min_lead_hours should be excluded."""
        rule = _make_rule(
            booking_interval=BookingInterval(min_lead_hours=24, slot_granularity_minutes=60),
        )

        with patch(f"{CALC_MODULE}.Appointment.objects") as mock_appt, \
             patch(f"{CALC_MODULE}.get_provider_display", return_value={"name": ""}), \
             patch(f"{CALC_MODULE}.Event.objects") as mock_evt, \
             patch(f"{CALC_MODULE}.get_blocks_for_provider", return_value=[]), \
             patch(f"{CALC_MODULE}.get_recurring_blocks_for_provider", return_value=[]):
            mock_appt.filter.return_value.values_list.return_value = []
            mock_evt.filter.return_value.exclude.return_value = []

            # now is Sunday 8am, lead time is 24h, so earliest bookable is Monday 8am.
            # Monday 9-12 window → slots at 9, 10, 11 are all bookable.
            slots = calculate_available_slots(
                rule, date(2026, 3, 9), date(2026, 3, 9),
                now=datetime(2026, 3, 8, 8, 0),
            )
            assert len(slots) == 3

            # now is Monday 8am, lead time is 24h → earliest bookable is Tuesday 8am.
            # Monday 9-12 window is entirely before Tuesday 8am → no slots.
            slots = calculate_available_slots(
                rule, date(2026, 3, 9), date(2026, 3, 9),
                now=datetime(2026, 3, 9, 8, 0),
            )
            assert len(slots) == 0

    def test_date_override_closed(self):
        """A closed date override should produce no slots on that day."""
        rule = _make_rule(
            date_overrides=[DateOverride(date=date(2026, 3, 9), is_closed=True)],
        )

        with patch(f"{CALC_MODULE}.Appointment.objects") as mock_appt, \
             patch(f"{CALC_MODULE}.get_provider_display", return_value={"name": ""}), \
             patch(f"{CALC_MODULE}.Event.objects") as mock_evt, \
             patch(f"{CALC_MODULE}.get_blocks_for_provider", return_value=[]), \
             patch(f"{CALC_MODULE}.get_recurring_blocks_for_provider", return_value=[]):
            mock_appt.filter.return_value.values_list.return_value = []
            mock_evt.filter.return_value.exclude.return_value = []

            slots = calculate_available_slots(
                rule, date(2026, 3, 9), date(2026, 3, 9),
                now=datetime(2026, 3, 1, 0, 0),
            )
            assert len(slots) == 0

    def test_date_override_modified_hours(self):
        """A date override with custom time windows should replace the weekly schedule."""
        rule = _make_rule(
            date_overrides=[
                DateOverride(
                    date=date(2026, 3, 9),
                    is_closed=False,
                    time_windows=[TimeWindow(start=dt.time(10, 0), end=dt.time(11, 0))],
                )
            ],
        )

        with patch(f"{CALC_MODULE}.Appointment.objects") as mock_appt, \
             patch(f"{CALC_MODULE}.get_provider_display", return_value={"name": ""}), \
             patch(f"{CALC_MODULE}.Event.objects") as mock_evt, \
             patch(f"{CALC_MODULE}.get_blocks_for_provider", return_value=[]), \
             patch(f"{CALC_MODULE}.get_recurring_blocks_for_provider", return_value=[]):
            mock_appt.filter.return_value.values_list.return_value = []
            mock_evt.filter.return_value.exclude.return_value = []

            slots = calculate_available_slots(
                rule, date(2026, 3, 9), date(2026, 3, 9),
                now=datetime(2026, 3, 1, 0, 0),
            )
            # 10:00-11:00 with 60-min granularity = 1 slot
            assert len(slots) == 1
            assert slots[0].start == datetime(2026, 3, 9, 10, 0)

    def test_blocked_by_appointment(self):
        """An existing appointment should block the overlapping slot."""
        rule = _make_rule()

        with patch(f"{CALC_MODULE}.Appointment.objects") as mock_appt, \
             patch(f"{CALC_MODULE}.get_provider_display", return_value={"name": ""}), \
             patch(f"{CALC_MODULE}.Event.objects") as mock_evt, \
             patch(f"{CALC_MODULE}.get_blocks_for_provider", return_value=[]), \
             patch(f"{CALC_MODULE}.get_recurring_blocks_for_provider", return_value=[]):
            # Appointment at 10:00 for 60 min blocks the 10:00-11:00 slot
            mock_appt.filter.return_value.values_list.return_value = [
                (datetime(2026, 3, 9, 10, 0), 60),
            ]
            mock_evt.filter.return_value.exclude.return_value = []

            slots = calculate_available_slots(
                rule, date(2026, 3, 9), date(2026, 3, 9),
                now=datetime(2026, 3, 1, 0, 0),
            )
            # 9-10 and 11-12 should be available, 10-11 blocked
            assert len(slots) == 2
            starts = [s.start for s in slots]
            assert datetime(2026, 3, 9, 10, 0) not in starts

    def test_effective_date_range(self):
        """Rule should only produce slots within its effective date range."""
        rule = _make_rule(
            effective_start=date(2026, 3, 16),
            effective_end=date(2026, 3, 22),
        )

        with patch(f"{CALC_MODULE}.Appointment.objects") as mock_appt, \
             patch(f"{CALC_MODULE}.get_provider_display", return_value={"name": ""}), \
             patch(f"{CALC_MODULE}.Event.objects") as mock_evt, \
             patch(f"{CALC_MODULE}.get_blocks_for_provider", return_value=[]), \
             patch(f"{CALC_MODULE}.get_recurring_blocks_for_provider", return_value=[]):
            mock_appt.filter.return_value.values_list.return_value = []
            mock_evt.filter.return_value.exclude.return_value = []

            # Query range starts before effective_start → no Monday in effective range
            slots = calculate_available_slots(
                rule, date(2026, 3, 9), date(2026, 3, 9),
                now=datetime(2026, 3, 1, 0, 0),
            )
            assert len(slots) == 0

            # Query within effective range — Monday 3/16 has slots
            slots = calculate_available_slots(
                rule, date(2026, 3, 16), date(2026, 3, 22),
                now=datetime(2026, 3, 1, 0, 0),
            )
            assert len(slots) == 3

    def test_no_schedule_for_day(self):
        """A day with no scheduled windows should produce no slots."""
        rule = _make_rule()  # Only Monday

        with patch(f"{CALC_MODULE}.Appointment.objects") as mock_appt, \
             patch(f"{CALC_MODULE}.get_provider_display", return_value={"name": ""}), \
             patch(f"{CALC_MODULE}.Event.objects") as mock_evt, \
             patch(f"{CALC_MODULE}.get_blocks_for_provider", return_value=[]), \
             patch(f"{CALC_MODULE}.get_recurring_blocks_for_provider", return_value=[]):
            mock_appt.filter.return_value.values_list.return_value = []
            mock_evt.filter.return_value.exclude.return_value = []

            # Tuesday 2026-03-10 — no schedule
            slots = calculate_available_slots(
                rule, date(2026, 3, 10), date(2026, 3, 10),
                now=datetime(2026, 3, 1, 0, 0),
            )
            assert len(slots) == 0

    def test_admin_block_subtracts_slots(self):
        """Admin blocks should remove overlapping slots."""
        rule = _make_rule()
        admin_block = AdminBlock(
            id="ab1", provider_id="p1",
            start=datetime(2026, 3, 9, 10, 0),
            end=datetime(2026, 3, 9, 11, 0),
        )

        with patch(f"{CALC_MODULE}.Appointment.objects") as mock_appt, \
             patch(f"{CALC_MODULE}.get_provider_display", return_value={"name": ""}), \
             patch(f"{CALC_MODULE}.Event.objects") as mock_evt, \
             patch(f"{CALC_MODULE}.get_blocks_for_provider", return_value=[admin_block]), \
             patch(f"{CALC_MODULE}.get_recurring_blocks_for_provider", return_value=[]):
            mock_appt.filter.return_value.values_list.return_value = []
            mock_evt.filter.return_value.exclude.return_value = []

            slots = calculate_available_slots(
                rule, date(2026, 3, 9), date(2026, 3, 9),
                now=datetime(2026, 3, 1, 0, 0),
            )
            assert len(slots) == 2
            starts = [s.start for s in slots]
            assert datetime(2026, 3, 9, 10, 0) not in starts

    def test_slot_metadata(self):
        """Slots should carry provider_id, location_id, and visit_type."""
        rule = _make_rule()

        with patch(f"{CALC_MODULE}.Appointment.objects") as mock_appt, \
             patch(f"{CALC_MODULE}.get_provider_display", return_value={"name": ""}), \
             patch(f"{CALC_MODULE}.Event.objects") as mock_evt, \
             patch(f"{CALC_MODULE}.get_blocks_for_provider", return_value=[]), \
             patch(f"{CALC_MODULE}.get_recurring_blocks_for_provider", return_value=[]):
            mock_appt.filter.return_value.values_list.return_value = []
            mock_evt.filter.return_value.exclude.return_value = []

            slots = calculate_available_slots(
                rule, date(2026, 3, 9), date(2026, 3, 9),
                now=datetime(2026, 3, 1, 0, 0),
            )
            assert slots[0].provider_id == "p1"
            assert slots[0].location_id == "loc-1"
            assert slots[0].visit_type == "vt-1"


# ── get_available_slots_for_provider ──────────────────────────────────


class TestGetAvailableSlotsForProvider:
    def test_filters_by_location(self):
        """Rules with non-matching location should be skipped."""
        rule = _make_rule(location_ids=["loc-other"])

        with patch(f"{CALC_MODULE}.Appointment.objects") as mock_appt, \
             patch(f"{CALC_MODULE}.get_provider_display", return_value={"name": ""}), \
             patch(f"{CALC_MODULE}.Event.objects") as mock_evt, \
             patch(f"{CALC_MODULE}.get_blocks_for_provider", return_value=[]), \
             patch(f"{CALC_MODULE}.get_recurring_blocks_for_provider", return_value=[]):
            mock_appt.filter.return_value.values_list.return_value = []
            mock_evt.filter.return_value.exclude.return_value = []

            slots = get_available_slots_for_provider(
                [rule], date(2026, 3, 9), date(2026, 3, 9),
                location_id="loc-1",
                now=datetime(2026, 3, 1, 0, 0),
            )
            assert len(slots) == 0

    def test_filters_by_visit_type(self):
        """Rules with non-matching visit type should be skipped."""
        rule = _make_rule(visit_types=["vt-other"])

        with patch(f"{CALC_MODULE}.Appointment.objects") as mock_appt, \
             patch(f"{CALC_MODULE}.get_provider_display", return_value={"name": ""}), \
             patch(f"{CALC_MODULE}.Event.objects") as mock_evt, \
             patch(f"{CALC_MODULE}.get_blocks_for_provider", return_value=[]), \
             patch(f"{CALC_MODULE}.get_recurring_blocks_for_provider", return_value=[]):
            mock_appt.filter.return_value.values_list.return_value = []
            mock_evt.filter.return_value.exclude.return_value = []

            slots = get_available_slots_for_provider(
                [rule], date(2026, 3, 9), date(2026, 3, 9),
                visit_type="vt-1",
                now=datetime(2026, 3, 1, 0, 0),
            )
            assert len(slots) == 0

    def test_empty_location_ids_matches_any(self):
        """Rules with empty location_ids should match any location filter."""
        rule = _make_rule(location_ids=[])

        with patch(f"{CALC_MODULE}.Appointment.objects") as mock_appt, \
             patch(f"{CALC_MODULE}.get_provider_display", return_value={"name": ""}), \
             patch(f"{CALC_MODULE}.Event.objects") as mock_evt, \
             patch(f"{CALC_MODULE}.get_blocks_for_provider", return_value=[]), \
             patch(f"{CALC_MODULE}.get_recurring_blocks_for_provider", return_value=[]):
            mock_appt.filter.return_value.values_list.return_value = []
            mock_evt.filter.return_value.exclude.return_value = []

            slots = get_available_slots_for_provider(
                [rule], date(2026, 3, 9), date(2026, 3, 9),
                location_id="loc-any",
                now=datetime(2026, 3, 1, 0, 0),
            )
            assert len(slots) == 3

    def test_now_defaults_to_practice_now(self):
        """When now is None, calculator should call provider_now()."""
        rule = _make_rule()

        with patch(f"{CALC_MODULE}.Appointment.objects") as mock_appt, \
             patch(f"{CALC_MODULE}.get_provider_display", return_value={"name": ""}), \
             patch(f"{CALC_MODULE}.Event.objects") as mock_evt, \
             patch(f"{CALC_MODULE}.get_blocks_for_provider", return_value=[]), \
             patch(f"{CALC_MODULE}.get_recurring_blocks_for_provider", return_value=[]), \
             patch(f"{CALC_MODULE}.provider_now", return_value=datetime(2026, 3, 1, 0, 0)) as mock_pn:
            mock_appt.filter.return_value.values_list.return_value = []
            mock_evt.filter.return_value.exclude.return_value = []

            slots = calculate_available_slots(
                rule, date(2026, 3, 9), date(2026, 3, 9),
                now=None,
            )
            assert mock_pn.mock_calls == [call(rule.provider_id)]
            assert len(slots) == 3

    def test_recurring_block_hold_same_day(self):
        """Hold type 'same_day' should block slots beyond today."""
        rule = _make_rule(
            weekly_schedule={
                "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
                "tuesday": [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
            },
        )
        # Recurring block with same_day hold on Tuesday
        rb = RecurringBlock(
            id="rb1", provider_id="p1",
            is_active=True,
            hold_type="same_day",
            weekly_schedule={
                "tuesday": [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
            },
        )

        with patch(f"{CALC_MODULE}.Appointment.objects") as mock_appt, \
             patch(f"{CALC_MODULE}.get_provider_display", return_value={"name": ""}), \
             patch(f"{CALC_MODULE}.Event.objects") as mock_evt, \
             patch(f"{CALC_MODULE}.get_blocks_for_provider", return_value=[]), \
             patch(f"{CALC_MODULE}.get_recurring_blocks_for_provider", return_value=[rb]):
            mock_appt.filter.return_value.values_list.return_value = []
            mock_evt.filter.return_value.exclude.return_value = []

            # now = Monday. same_day blocks slots > today, so Tuesday (tomorrow) is blocked
            slots = calculate_available_slots(
                rule, date(2026, 3, 9), date(2026, 3, 10),
                now=datetime(2026, 3, 9, 0, 0),
            )
            # Monday should have 3 slots, Tuesday blocked by hold
            monday_slots = [s for s in slots if s.start.date() == date(2026, 3, 9)]
            tuesday_slots = [s for s in slots if s.start.date() == date(2026, 3, 10)]
            assert len(monday_slots) == 3
            assert len(tuesday_slots) == 0

    def test_recurring_block_hold_next_day(self):
        """Hold type 'next_day' should block slots more than 1 day out."""
        rule = _make_rule(
            weekly_schedule={
                "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
                "tuesday": [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
                "wednesday": [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
            },
        )
        rb = RecurringBlock(
            id="rb1", provider_id="p1",
            is_active=True,
            hold_type="next_day",
            weekly_schedule={
                "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
                "tuesday": [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
                "wednesday": [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
            },
        )

        with patch(f"{CALC_MODULE}.Appointment.objects") as mock_appt, \
             patch(f"{CALC_MODULE}.get_provider_display", return_value={"name": ""}), \
             patch(f"{CALC_MODULE}.Event.objects") as mock_evt, \
             patch(f"{CALC_MODULE}.get_blocks_for_provider", return_value=[]), \
             patch(f"{CALC_MODULE}.get_recurring_blocks_for_provider", return_value=[rb]):
            mock_appt.filter.return_value.values_list.return_value = []
            mock_evt.filter.return_value.exclude.return_value = []

            # now = Monday. next_day blocks > today+1, so Wednesday is blocked but Tuesday is not
            slots = calculate_available_slots(
                rule, date(2026, 3, 9), date(2026, 3, 11),
                now=datetime(2026, 3, 9, 0, 0),
            )
            monday_slots = [s for s in slots if s.start.date() == date(2026, 3, 9)]
            tuesday_slots = [s for s in slots if s.start.date() == date(2026, 3, 10)]
            wednesday_slots = [s for s in slots if s.start.date() == date(2026, 3, 11)]
            assert len(monday_slots) == 3  # today - not blocked
            assert len(tuesday_slots) == 3  # tomorrow - not blocked by next_day
            assert len(wednesday_slots) == 0  # 2 days out - blocked

    def test_recurring_block_none_hold_type_not_blocked(self):
        """Hold type 'none' recurring blocks are handled by calendar events, not calculator."""
        rule = _make_rule()
        rb = RecurringBlock(
            id="rb1", provider_id="p1",
            is_active=True,
            hold_type="none",
            weekly_schedule={
                "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
            },
        )

        with patch(f"{CALC_MODULE}.Appointment.objects") as mock_appt, \
             patch(f"{CALC_MODULE}.get_provider_display", return_value={"name": ""}), \
             patch(f"{CALC_MODULE}.Event.objects") as mock_evt, \
             patch(f"{CALC_MODULE}.get_blocks_for_provider", return_value=[]), \
             patch(f"{CALC_MODULE}.get_recurring_blocks_for_provider", return_value=[rb]):
            mock_appt.filter.return_value.values_list.return_value = []
            mock_evt.filter.return_value.exclude.return_value = []

            slots = calculate_available_slots(
                rule, date(2026, 3, 9), date(2026, 3, 9),
                now=datetime(2026, 3, 1, 0, 0),
            )
            # hold_type=none → not blocked by calculator
            assert len(slots) == 3

    def test_recurring_block_with_effective_date_range(self):
        """Recurring blocks should respect effective_start/effective_end."""
        rule = _make_rule(
            weekly_schedule={
                "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
            },
        )
        rb = RecurringBlock(
            id="rb1", provider_id="p1",
            is_active=True,
            hold_type="same_day",
            effective_start=date(2026, 3, 16),  # starts next week
            effective_end=date(2026, 3, 22),
            weekly_schedule={
                "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
            },
        )

        with patch(f"{CALC_MODULE}.Appointment.objects") as mock_appt, \
             patch(f"{CALC_MODULE}.get_provider_display", return_value={"name": ""}), \
             patch(f"{CALC_MODULE}.Event.objects") as mock_evt, \
             patch(f"{CALC_MODULE}.get_blocks_for_provider", return_value=[]), \
             patch(f"{CALC_MODULE}.get_recurring_blocks_for_provider", return_value=[rb]):
            mock_appt.filter.return_value.values_list.return_value = []
            mock_evt.filter.return_value.exclude.return_value = []

            # March 9 is before effective_start → not blocked
            slots = calculate_available_slots(
                rule, date(2026, 3, 9), date(2026, 3, 9),
                now=datetime(2026, 3, 1, 0, 0),
            )
            assert len(slots) == 3

    def test_schedule_event_blocks(self):
        """Canvas Schedule Events should block overlapping slots."""
        rule = _make_rule()

        mock_event = MagicMock()
        mock_event.starts_at = datetime(2026, 3, 9, 10, 0)
        mock_event.ends_at = datetime(2026, 3, 9, 11, 0)

        with patch(f"{CALC_MODULE}.Appointment.objects") as mock_appt, \
             patch(f"{CALC_MODULE}.get_provider_display", return_value={"name": "Dr. Jane Doe"}), \
             patch(f"{CALC_MODULE}.Event.objects") as mock_evt, \
             patch(f"{CALC_MODULE}.get_blocks_for_provider", return_value=[]), \
             patch(f"{CALC_MODULE}.get_recurring_blocks_for_provider", return_value=[]), \
             patch(f"{CALC_MODULE}.to_provider_naive", side_effect=lambda x, _pid: x):
            mock_appt.filter.return_value.values_list.return_value = []
            mock_evt.filter.return_value.exclude.return_value = [mock_event]

            slots = calculate_available_slots(
                rule, date(2026, 3, 9), date(2026, 3, 9),
                now=datetime(2026, 3, 1, 0, 0),
            )
            # 10-11 blocked by schedule event → 2 slots
            assert len(slots) == 2

    def test_slots_sorted_by_start(self):
        """Results from multiple rules should be sorted by start time."""
        rule_am = _make_rule(
            id="r1",
            weekly_schedule={"monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(10, 0))]},
        )
        rule_pm = _make_rule(
            id="r2",
            weekly_schedule={"monday": [TimeWindow(start=dt.time(14, 0), end=dt.time(15, 0))]},
        )

        with patch(f"{CALC_MODULE}.Appointment.objects") as mock_appt, \
             patch(f"{CALC_MODULE}.get_provider_display", return_value={"name": ""}), \
             patch(f"{CALC_MODULE}.Event.objects") as mock_evt, \
             patch(f"{CALC_MODULE}.get_blocks_for_provider", return_value=[]), \
             patch(f"{CALC_MODULE}.get_recurring_blocks_for_provider", return_value=[]):
            mock_appt.filter.return_value.values_list.return_value = []
            mock_evt.filter.return_value.exclude.return_value = []

            slots = get_available_slots_for_provider(
                [rule_pm, rule_am], date(2026, 3, 9), date(2026, 3, 9),
                now=datetime(2026, 3, 1, 0, 0),
            )
            assert slots[0].start < slots[1].start
