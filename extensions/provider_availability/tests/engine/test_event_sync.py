"""Tests for provider_availability.engine.event_sync."""

import datetime as dt
from datetime import UTC, date, datetime
from unittest.mock import MagicMock, call, patch
from zoneinfo import ZoneInfo

import pytest

from canvas_sdk.effects.calendar import CalendarType, EventRecurrence

from provider_availability.engine.models import (
    AdminBlock,
    BookingInterval,
    DateOverride,
    ProviderAvailabilityRule,
    RecurringBlock,
    TimeWindow,
)
from provider_availability.engine.event_sync import (
    AVAILABILITY_TITLE,
    BLOCK_TITLE,
    LEAD_TIME_TITLE,
    LEAD_TIME_DRIFT_THRESHOLD_SECONDS,
    HOLD_BLOCK_TITLE,
    OVERRIDE_BLOCK_TITLE,
    RECURRING_BLOCK_TITLE,
    _compute_recurring_segments,
    _next_weekday,
    _weekday_occurrences,
    _build_hold_block_events,
    _build_rule_events,
    _get_calendar_id,
    build_block_event_effects,
    build_hold_block_refresh_effects,
    build_delete_block_effects,
    build_delete_effects,
    build_delete_recurring_block_effects,
    build_lead_time_block_effects,
    build_recurring_block_sync_effects,
    build_sync_effects,
    delete_all_lead_time_events,
    sync_provider_availability,
)

MODULE = "provider_availability.engine.event_sync"
PROVIDER_ID = "provider-uuid-123"
LOCATION_ID = "location-uuid-456"


# ── _next_weekday ─────────────────────────────────────────────────────


class TestNextWeekday:
    def test_same_day(self):
        # 2026-03-02 is a Monday (weekday 0)
        result = _next_weekday(date(2026, 3, 2), 0)
        assert result == date(2026, 3, 2)

    def test_next_day(self):
        # From Monday, find Tuesday (weekday 1)
        result = _next_weekday(date(2026, 3, 2), 1)
        assert result == date(2026, 3, 3)

    def test_wraps_around(self):
        # From Wednesday (2026-03-04), find Monday (weekday 0)
        result = _next_weekday(date(2026, 3, 4), 0)
        assert result == date(2026, 3, 9)

    def test_friday_from_monday(self):
        result = _next_weekday(date(2026, 3, 2), 4)
        assert result == date(2026, 3, 6)

    def test_sunday_from_saturday(self):
        # 2026-03-07 is Saturday (weekday 5), find Sunday (weekday 6)
        result = _next_weekday(date(2026, 3, 7), 6)
        assert result == date(2026, 3, 8)

    def test_same_weekday_returns_same_date(self):
        # 2026-03-06 is Friday (weekday 4)
        result = _next_weekday(date(2026, 3, 6), 4)
        assert result == date(2026, 3, 6)

    def test_sunday_wraps_to_next_week(self):
        # From Sunday (weekday 6), find Saturday (weekday 5) = next Sat
        result = _next_weekday(date(2026, 3, 8), 5)  # 2026-03-08 is Sunday
        assert result == date(2026, 3, 14)


# ── _weekday_occurrences ──────────────────────────────────────────────


class TestWeekdayOccurrences:
    def test_full_month_mondays(self):
        result = _weekday_occurrences(date(2026, 3, 1), date(2026, 3, 31), 0)
        assert result == [
            date(2026, 3, 2),
            date(2026, 3, 9),
            date(2026, 3, 16),
            date(2026, 3, 23),
            date(2026, 3, 30),
        ]

    def test_no_occurrences(self):
        # Range too short to contain Friday (weekday 4)
        # 2026-03-02 is Monday, 2026-03-05 is Thursday
        result = _weekday_occurrences(date(2026, 3, 2), date(2026, 3, 5), 4)
        assert result == []

    def test_single_day_match(self):
        # 2026-03-02 is Monday
        result = _weekday_occurrences(date(2026, 3, 2), date(2026, 3, 2), 0)
        assert result == [date(2026, 3, 2)]

    def test_single_day_no_match(self):
        result = _weekday_occurrences(date(2026, 3, 2), date(2026, 3, 2), 1)
        assert result == []

    def test_two_week_span(self):
        # Two Wednesdays in a two-week span starting on a Monday
        result = _weekday_occurrences(date(2026, 3, 2), date(2026, 3, 15), 2)
        assert result == [date(2026, 3, 4), date(2026, 3, 11)]

    def test_start_equals_end_on_matching_day(self):
        # 2026-03-06 is a Friday
        result = _weekday_occurrences(date(2026, 3, 6), date(2026, 3, 6), 4)
        assert result == [date(2026, 3, 6)]


# ── sync_provider_availability ────────────────────────────────────────


class TestSyncProviderAvailability:
    @patch(f"{MODULE}._build_rule_events")
    @patch(f"{MODULE}.get_rules_for_provider")
    @patch(f"{MODULE}.build_delete_effects")
    def test_active_rules_sync(
        self, mock_delete, mock_get_rules, mock_build_events, sample_rule
    ):
        delete_effect = MagicMock()
        mock_delete.return_value = [delete_effect]

        event_effect = MagicMock()
        mock_build_events.return_value = [event_effect]

        mock_get_rules.return_value = [sample_rule]

        result = sync_provider_availability(PROVIDER_ID)

        assert mock_delete.mock_calls == [call(PROVIDER_ID)]
        assert mock_get_rules.mock_calls == [call(PROVIDER_ID)]
        assert mock_build_events.mock_calls == [call(sample_rule)]
        assert result == [delete_effect, event_effect]

    @patch(f"{MODULE}._build_rule_events")
    @patch(f"{MODULE}.get_rules_for_provider")
    @patch(f"{MODULE}.build_delete_effects")
    def test_inactive_rules_skipped(
        self, mock_delete, mock_get_rules, mock_build_events, sample_rule
    ):
        sample_rule.is_active = False
        mock_delete.return_value = []
        mock_get_rules.return_value = [sample_rule]

        result = sync_provider_availability(PROVIDER_ID)

        assert mock_delete.mock_calls == [call(PROVIDER_ID)]
        assert mock_get_rules.mock_calls == [call(PROVIDER_ID)]
        assert mock_build_events.mock_calls == []
        assert result == []

    @patch(f"{MODULE}._build_rule_events")
    @patch(f"{MODULE}.get_rules_for_provider")
    @patch(f"{MODULE}.build_delete_effects")
    def test_no_weekly_schedule_skipped(
        self, mock_delete, mock_get_rules, mock_build_events
    ):
        rule = ProviderAvailabilityRule(
            id="rule-1",
            provider_id=PROVIDER_ID,
            is_active=True,
            weekly_schedule={},
        )
        mock_delete.return_value = []
        mock_get_rules.return_value = [rule]

        result = sync_provider_availability(PROVIDER_ID)

        assert mock_build_events.mock_calls == []
        assert result == []

    @patch(f"{MODULE}._build_rule_events")
    @patch(f"{MODULE}.get_rules_for_provider")
    @patch(f"{MODULE}.build_delete_effects")
    def test_multiple_active_rules(
        self, mock_delete, mock_get_rules, mock_build_events
    ):
        rule1 = ProviderAvailabilityRule(
            id="rule-1",
            provider_id=PROVIDER_ID,
            is_active=True,
            weekly_schedule={
                "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
            },
        )
        rule2 = ProviderAvailabilityRule(
            id="rule-2",
            provider_id=PROVIDER_ID,
            is_active=True,
            weekly_schedule={
                "tuesday": [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
            },
        )
        mock_delete.return_value = []
        mock_get_rules.return_value = [rule1, rule2]
        eff1, eff2 = MagicMock(), MagicMock()
        mock_build_events.side_effect = [[eff1], [eff2]]

        result = sync_provider_availability(PROVIDER_ID)

        assert mock_build_events.mock_calls == [call(rule1), call(rule2)]
        assert result == [eff1, eff2]

    @patch(f"{MODULE}._build_rule_events")
    @patch(f"{MODULE}.get_rules_for_provider")
    @patch(f"{MODULE}.build_delete_effects")
    def test_no_rules_returns_only_delete_effects(
        self, mock_delete, mock_get_rules, mock_build_events
    ):
        delete_eff = MagicMock()
        mock_delete.return_value = [delete_eff]
        mock_get_rules.return_value = []

        result = sync_provider_availability(PROVIDER_ID)

        assert mock_build_events.mock_calls == []
        assert result == [delete_eff]

    @patch(f"{MODULE}._build_rule_events")
    @patch(f"{MODULE}.get_rules_for_provider")
    @patch(f"{MODULE}.build_delete_effects")
    def test_mix_active_and_inactive(
        self, mock_delete, mock_get_rules, mock_build_events
    ):
        active = ProviderAvailabilityRule(
            id="r-active",
            provider_id=PROVIDER_ID,
            is_active=True,
            weekly_schedule={
                "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
            },
        )
        inactive = ProviderAvailabilityRule(
            id="r-inactive",
            provider_id=PROVIDER_ID,
            is_active=False,
            weekly_schedule={
                "tuesday": [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
            },
        )
        mock_delete.return_value = []
        mock_get_rules.return_value = [active, inactive]
        mock_build_events.return_value = [MagicMock()]

        result = sync_provider_availability(PROVIDER_ID)

        # Only the active rule should be built
        assert mock_build_events.mock_calls == [call(active)]
        assert len(result) == 1


# ── build_sync_effects ────────────────────────────────────────────────


class TestBuildSyncEffects:
    @patch(f"{MODULE}._build_rule_events")
    @patch(f"{MODULE}.build_delete_effects")
    def test_delegates_to_delete_and_build(
        self, mock_delete, mock_build_events, sample_rule
    ):
        del_eff = MagicMock()
        build_eff = MagicMock()
        mock_delete.return_value = [del_eff]
        mock_build_events.return_value = [build_eff]

        result = build_sync_effects(sample_rule)

        assert mock_delete.mock_calls == [call(sample_rule.provider_id)]
        assert mock_build_events.mock_calls == [call(sample_rule)]
        assert result == [del_eff, build_eff]

    @patch(f"{MODULE}._build_rule_events")
    @patch(f"{MODULE}.build_delete_effects")
    def test_empty_both(self, mock_delete, mock_build_events, sample_rule):
        mock_delete.return_value = []
        mock_build_events.return_value = []

        result = build_sync_effects(sample_rule)

        assert result == []


# ── build_delete_effects ─────────────────────────────────────────────


class TestBuildDeleteEffects:
    def test_provider_not_found(self):
        from canvas_sdk.v1.data.staff import Staff

        with patch(f"{MODULE}.Staff.objects") as mock_staff_objects:
            mock_staff_objects.get.side_effect = Staff.DoesNotExist

            result = build_delete_effects(PROVIDER_ID)

            assert mock_staff_objects.mock_calls == [call.get(id=PROVIDER_ID)]
            assert result == []

    def test_empty_provider_name(self):
        mock_staff = MagicMock()
        mock_staff.full_name = ""

        with patch(f"{MODULE}.Staff.objects") as mock_staff_objects:
            mock_staff_objects.get.return_value = mock_staff

            result = build_delete_effects(PROVIDER_ID)

            assert result == []

    def test_no_calendars(self):
        mock_staff = MagicMock()
        mock_staff.full_name = "Jane Doe"

        with patch(f"{MODULE}.Staff.objects") as mock_staff_objects, \
             patch(f"{MODULE}.CalendarModel.objects") as mock_cal_objects:
            mock_staff_objects.get.return_value = mock_staff
            mock_cal_objects.filter.return_value = []

            result = build_delete_effects(PROVIDER_ID)

            assert mock_cal_objects.mock_calls == [
                call.filter(title__startswith="Jane Doe: Clinic"),
            ]
            assert result == []

    def test_deletes_matching_events(self):
        mock_staff = MagicMock()
        mock_staff.full_name = "Jane Doe"

        mock_cal = MagicMock()
        mock_cal.id = "cal-uuid-1"
        mock_cal.title = "Jane Doe: Clinic"

        future = datetime.now(UTC) + dt.timedelta(days=7)
        mock_evt1 = MagicMock()
        mock_evt1.id = "evt-uuid-1"
        mock_evt1.ends_at = future
        mock_evt1.recurrence_ends_at = None
        mock_evt2 = MagicMock()
        mock_evt2.id = "evt-uuid-2"
        mock_evt2.ends_at = future
        mock_evt2.recurrence_ends_at = None

        mock_qs = MagicMock()
        mock_qs.__iter__ = MagicMock(return_value=iter([mock_evt1, mock_evt2]))

        with patch(f"{MODULE}.Staff.objects") as mock_staff_objects, \
             patch(f"{MODULE}.CalendarModel.objects") as mock_cal_objects, \
             patch(f"{MODULE}.EventModel.objects") as mock_event_objects:
            mock_staff_objects.get.return_value = mock_staff
            mock_cal_objects.filter.return_value = [mock_cal]
            mock_event_objects.filter.return_value = mock_qs

            result = build_delete_effects(PROVIDER_ID)

            assert mock_staff_objects.mock_calls == [call.get(id=PROVIDER_ID)]
            assert len(result) == 2

    def test_multiple_calendars(self):
        mock_staff = MagicMock()
        mock_staff.full_name = "Jane Doe"

        mock_cal1 = MagicMock()
        mock_cal1.id = "cal-1"
        mock_cal1.title = "Jane Doe: Clinic"
        mock_cal2 = MagicMock()
        mock_cal2.id = "cal-2"
        mock_cal2.title = "Jane Doe: Clinic: West"

        future = datetime.now(UTC) + dt.timedelta(days=7)
        mock_evt1 = MagicMock()
        mock_evt1.id = "evt-1"
        mock_evt1.ends_at = future
        mock_evt1.recurrence_ends_at = None
        mock_evt2 = MagicMock()
        mock_evt2.id = "evt-2"
        mock_evt2.ends_at = future
        mock_evt2.recurrence_ends_at = None

        mock_qs = MagicMock()
        mock_qs.__iter__ = MagicMock(return_value=iter([mock_evt1, mock_evt2]))

        with patch(f"{MODULE}.Staff.objects") as mock_staff_objects, \
             patch(f"{MODULE}.CalendarModel.objects") as mock_cal_objects, \
             patch(f"{MODULE}.EventModel.objects") as mock_event_objects:
            mock_staff_objects.get.return_value = mock_staff
            mock_cal_objects.filter.return_value = [mock_cal1, mock_cal2]
            mock_event_objects.filter.return_value = mock_qs

            result = build_delete_effects(PROVIDER_ID)

            # One bulk query across all the provider's Clinic calendars
            assert mock_event_objects.filter.call_args_list == [
                call(
                    calendar__id__in=["cal-1", "cal-2"],
                    title=AVAILABILITY_TITLE,
                    is_cancelled=False,
                )
            ]
            # 2 events total (one from each calendar)
            assert len(result) == 2

    def test_calendars_with_no_events(self):
        mock_staff = MagicMock()
        mock_staff.full_name = "Jane Doe"

        mock_cal = MagicMock()
        mock_cal.id = "cal-1"
        mock_cal.title = "Jane Doe: Clinic"

        mock_qs = MagicMock()
        mock_qs.__iter__ = MagicMock(return_value=iter([]))

        with patch(f"{MODULE}.Staff.objects") as mock_staff_objects, \
             patch(f"{MODULE}.CalendarModel.objects") as mock_cal_objects, \
             patch(f"{MODULE}.EventModel.objects") as mock_event_objects:
            mock_staff_objects.get.return_value = mock_staff
            mock_cal_objects.filter.return_value = [mock_cal]
            mock_event_objects.filter.return_value = mock_qs

            result = build_delete_effects(PROVIDER_ID)

            assert result == []

    def test_skips_past_events(self):
        """Past events (ended before now) are preserved for historical reporting."""
        mock_staff = MagicMock()
        mock_staff.full_name = "Jane Doe"

        mock_cal = MagicMock()
        mock_cal.id = "cal-1"
        mock_cal.title = "Jane Doe: Clinic"

        past = datetime.now(UTC) - dt.timedelta(days=7)
        mock_evt = MagicMock()
        mock_evt.id = "evt-past"
        mock_evt.ends_at = past
        mock_evt.recurrence_ends_at = None

        mock_qs = MagicMock()
        mock_qs.__iter__ = MagicMock(return_value=iter([mock_evt]))

        with patch(f"{MODULE}.Staff.objects") as mock_staff_objects, \
             patch(f"{MODULE}.CalendarModel.objects") as mock_cal_objects, \
             patch(f"{MODULE}.EventModel.objects") as mock_event_objects:
            mock_staff_objects.get.return_value = mock_staff
            mock_cal_objects.filter.return_value = [mock_cal]
            mock_event_objects.filter.return_value = mock_qs

            result = build_delete_effects(PROVIDER_ID)

            assert result == []

    def test_deletes_recurring_event_spanning_future(self):
        """Recurring events whose recurrence extends into the future ARE deleted."""
        mock_staff = MagicMock()
        mock_staff.full_name = "Jane Doe"

        mock_cal = MagicMock()
        mock_cal.id = "cal-1"
        mock_cal.title = "Jane Doe: Clinic"

        past_start = datetime.now(UTC) - dt.timedelta(days=30)
        future_end = datetime.now(UTC) + dt.timedelta(days=30)
        mock_evt = MagicMock()
        mock_evt.id = "evt-recurring"
        mock_evt.ends_at = past_start
        mock_evt.recurrence_ends_at = future_end

        mock_qs = MagicMock()
        mock_qs.__iter__ = MagicMock(return_value=iter([mock_evt]))

        with patch(f"{MODULE}.Staff.objects") as mock_staff_objects, \
             patch(f"{MODULE}.CalendarModel.objects") as mock_cal_objects, \
             patch(f"{MODULE}.EventModel.objects") as mock_event_objects:
            mock_staff_objects.get.return_value = mock_staff
            mock_cal_objects.filter.return_value = [mock_cal]
            mock_event_objects.filter.return_value = mock_qs

            result = build_delete_effects(PROVIDER_ID)

            assert len(result) == 1


# ── _get_calendar_id ──────────────────────────────────────────────────


class TestGetCalendarId:
    def test_existing_calendar_found(self):
        mock_staff = MagicMock()
        mock_staff.full_name = "Jane Doe"

        mock_cal = MagicMock()
        mock_cal.id = "existing-cal-uuid"

        with patch(f"{MODULE}.Staff.objects") as mock_staff_objects, \
             patch(f"{MODULE}.CalendarModel.objects") as mock_cal_objects, \
             patch(f"{MODULE}.PracticeLocation.objects") as mock_loc_objects:
            mock_staff_objects.get.return_value = mock_staff
            mock_loc = MagicMock()
            mock_loc.full_name = "West Office"
            mock_loc_objects.get.return_value = mock_loc
            # anchor-id lookup misses -> falls back to title match
            mock_cal_objects.filter.return_value.first.return_value = None
            mock_cal_objects.for_calendar_name.return_value.first.return_value = mock_cal

            cal_id, effects = _get_calendar_id(PROVIDER_ID, LOCATION_ID)

            assert cal_id == "existing-cal-uuid"
            assert effects == []
            assert mock_cal_objects.for_calendar_name.call_args == call(
                provider_name="Jane Doe",
                calendar_type=CalendarType.Clinic,
                location="West Office",
            )

    def test_existing_calendar_found_by_anchor_id(self):
        """A calendar matching the deterministic anchor id is reused without a title lookup."""
        mock_staff = MagicMock()
        mock_staff.full_name = "Jane Doe"

        mock_cal = MagicMock()
        mock_cal.id = "anchor-cal-uuid"

        with patch(f"{MODULE}.Staff.objects") as mock_staff_objects, \
             patch(f"{MODULE}.CalendarModel.objects") as mock_cal_objects, \
             patch(f"{MODULE}.PracticeLocation.objects") as mock_loc_objects:
            mock_staff_objects.get.return_value = mock_staff
            mock_loc_objects.get.return_value = MagicMock(full_name="West Office")
            mock_cal_objects.filter.return_value.first.return_value = mock_cal

            cal_id, effects = _get_calendar_id(PROVIDER_ID, LOCATION_ID)

            assert cal_id == "anchor-cal-uuid"
            assert effects == []
            # title lookup is not consulted when the anchor id matches
            assert mock_cal_objects.for_calendar_name.call_count == 0

    def test_creates_new_calendar(self):
        mock_staff = MagicMock()
        mock_staff.full_name = "Jane Doe"

        with patch(f"{MODULE}.Staff.objects") as mock_staff_objects, \
             patch(f"{MODULE}.CalendarModel.objects") as mock_cal_objects, \
             patch(f"{MODULE}.PracticeLocation.objects") as mock_loc_objects, \
             patch(f"{MODULE}.deterministic_calendar_id", return_value="new-cal-uuid"):
            mock_staff_objects.get.return_value = mock_staff
            mock_loc = MagicMock()
            mock_loc.full_name = "West Office"
            mock_loc_objects.get.return_value = mock_loc
            mock_cal_objects.filter.return_value.first.return_value = None
            mock_cal_objects.for_calendar_name.return_value.first.return_value = None

            cal_id, effects = _get_calendar_id(PROVIDER_ID, LOCATION_ID)

            assert cal_id == "new-cal-uuid"
            assert len(effects) == 1

    def test_staff_not_found(self):
        from canvas_sdk.v1.data.staff import Staff

        with patch(f"{MODULE}.Staff.objects") as mock_staff_objects, \
             patch(f"{MODULE}.PracticeLocation.objects") as mock_loc_objects, \
             patch(f"{MODULE}.deterministic_calendar_id", return_value="new-cal-uuid"):
            mock_staff_objects.get.side_effect = Staff.DoesNotExist
            mock_loc = MagicMock()
            mock_loc.full_name = "West Office"
            mock_loc_objects.get.return_value = mock_loc

            cal_id, effects = _get_calendar_id(PROVIDER_ID, LOCATION_ID)

            # provider_name is empty, so creates a new calendar
            assert cal_id == "new-cal-uuid"
            assert len(effects) == 1

    def test_no_location_id(self):
        mock_staff = MagicMock()
        mock_staff.full_name = "Jane Doe"

        mock_cal = MagicMock()
        mock_cal.id = "existing-cal-uuid"

        with patch(f"{MODULE}.Staff.objects") as mock_staff_objects, \
             patch(f"{MODULE}.CalendarModel.objects") as mock_cal_objects:
            mock_staff_objects.get.return_value = mock_staff
            mock_cal_objects.filter.return_value.first.return_value = None
            mock_cal_objects.for_calendar_name.return_value.first.return_value = mock_cal

            cal_id, effects = _get_calendar_id(PROVIDER_ID, None)

            assert cal_id == "existing-cal-uuid"
            assert effects == []
            assert mock_cal_objects.for_calendar_name.call_args == call(
                provider_name="Jane Doe",
                calendar_type=CalendarType.Clinic,
                location=None,
            )

    def test_location_not_found_uses_empty_name(self):
        """When location_id is given but PracticeLocation.DoesNotExist, location_name is empty."""
        from canvas_sdk.v1.data import PracticeLocation

        mock_staff = MagicMock()
        mock_staff.full_name = "Jane Doe"
        mock_cal = MagicMock()
        mock_cal.id = "existing-cal-uuid"

        with patch(f"{MODULE}.Staff.objects") as mock_staff_objects, \
             patch(f"{MODULE}.CalendarModel.objects") as mock_cal_objects, \
             patch(f"{MODULE}.PracticeLocation.objects") as mock_loc_objects:
            mock_staff_objects.get.return_value = mock_staff
            mock_loc_objects.get.side_effect = PracticeLocation.DoesNotExist
            mock_cal_objects.filter.return_value.first.return_value = None
            mock_cal_objects.for_calendar_name.return_value.first.return_value = mock_cal

            cal_id, effects = _get_calendar_id(PROVIDER_ID, "bad-loc-id")

            assert cal_id == "existing-cal-uuid"
            assert effects == []
            # location=None because location_name is empty
            assert mock_cal_objects.for_calendar_name.call_args == call(
                provider_name="Jane Doe",
                calendar_type=CalendarType.Clinic,
                location=None,
            )

    def test_creates_calendar_with_location_id_passed(self):
        """New calendar creation passes location_id to CalendarEffect."""
        mock_staff = MagicMock()
        mock_staff.full_name = "Jane Doe"

        with patch(f"{MODULE}.Staff.objects") as mock_staff_objects, \
             patch(f"{MODULE}.CalendarModel.objects") as mock_cal_objects, \
             patch(f"{MODULE}.PracticeLocation.objects") as mock_loc_objects, \
             patch(f"{MODULE}.deterministic_calendar_id", return_value="new-id"), \
             patch(f"{MODULE}.CalendarEffect") as mock_cal_effect:
            mock_staff_objects.get.return_value = mock_staff
            mock_loc = MagicMock()
            mock_loc.full_name = "West"
            mock_loc_objects.get.return_value = mock_loc
            mock_cal_objects.filter.return_value.first.return_value = None
            mock_cal_objects.for_calendar_name.return_value.first.return_value = None
            mock_cal_effect.return_value.create.return_value = MagicMock()

            cal_id, effects = _get_calendar_id(PROVIDER_ID, LOCATION_ID)

            assert mock_cal_effect.mock_calls == [
                call(
                    id="new-id",
                    provider=PROVIDER_ID,
                    type=CalendarType.Clinic,
                    location=LOCATION_ID,
                    description=str(PROVIDER_ID),
                ),
                call().create(),
            ]
            assert cal_id == "new-id"

    def test_creates_calendar_without_location(self):
        """New calendar creation passes location=None when location_id is None."""
        mock_staff = MagicMock()
        mock_staff.full_name = ""  # empty name -> skip for_calendar_name

        with patch(f"{MODULE}.Staff.objects") as mock_staff_objects, \
             patch(f"{MODULE}.deterministic_calendar_id", return_value="new-id"), \
             patch(f"{MODULE}.CalendarEffect") as mock_cal_effect:
            mock_staff_objects.get.return_value = mock_staff
            mock_cal_effect.return_value.create.return_value = MagicMock()

            cal_id, effects = _get_calendar_id(PROVIDER_ID, None)

            assert mock_cal_effect.mock_calls == [
                call(
                    id="new-id",
                    provider=PROVIDER_ID,
                    type=CalendarType.Clinic,
                    location=None,
                    description=str(PROVIDER_ID),
                ),
                call().create(),
            ]


# ── _build_rule_events ────────────────────────────────────────────────


class TestBuildRuleEvents:
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}._get_calendar_id")
    def test_no_weekly_schedule_returns_empty(
        self, mock_get_cal, mock_tz
    ):
        rule = ProviderAvailabilityRule(
            id="rule-1",
            provider_id=PROVIDER_ID,
            weekly_schedule={},
        )
        result = _build_rule_events(rule)

        assert result == []
        assert mock_get_cal.mock_calls == []

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}._get_calendar_id")
    def test_single_location_single_day(
        self, mock_get_cal, mock_tz, mock_localize, mock_to_utc, sample_rule
    ):
        from zoneinfo import ZoneInfo

        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_cal.return_value = ("cal-uuid-1", [])

        # Fix date.today for deterministic results
        with patch(f"{MODULE}.date") as mock_date:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

            result = _build_rule_events(sample_rule)

        # sample_rule has monday (9-12) and wednesday (13-17), 1 location
        # = 2 event effects
        assert len(result) == 2

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}._get_calendar_id")
    def test_no_locations_uses_all_active(
        self, mock_get_cal, mock_tz, mock_localize, mock_to_utc
    ):
        from zoneinfo import ZoneInfo

        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_cal.return_value = ("cal-uuid-1", [])

        rule = ProviderAvailabilityRule(
            id="rule-1",
            provider_id=PROVIDER_ID,
            location_ids=[],  # no locations specified
            weekly_schedule={
                "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
            },
        )

        mock_loc1 = MagicMock()
        mock_loc1.id = "loc-1"
        mock_loc2 = MagicMock()
        mock_loc2.id = "loc-2"

        with patch(f"{MODULE}.date") as mock_date, \
             patch(f"{MODULE}.PracticeLocation.objects") as mock_loc_objects:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            mock_loc_objects.filter.return_value = [mock_loc1, mock_loc2]

            result = _build_rule_events(rule)

        # 1 day x 2 locations = 2 event effects
        assert len(result) == 2
        assert mock_get_cal.mock_calls == [
            call(PROVIDER_ID, "loc-1"),
            call(PROVIDER_ID, "loc-2"),
        ]

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}._get_calendar_id")
    def test_no_locations_no_active_returns_empty(
        self, mock_get_cal, mock_tz, mock_localize, mock_to_utc
    ):
        from zoneinfo import ZoneInfo

        mock_tz.return_value = ZoneInfo("US/Eastern")

        rule = ProviderAvailabilityRule(
            id="rule-1",
            provider_id=PROVIDER_ID,
            location_ids=[],
            weekly_schedule={
                "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
            },
        )

        with patch(f"{MODULE}.date") as mock_date, \
             patch(f"{MODULE}.PracticeLocation.objects") as mock_loc_objects:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            mock_loc_objects.filter.return_value = []

            result = _build_rule_events(rule)

        assert result == []
        assert mock_get_cal.mock_calls == []

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}._get_calendar_id")
    def test_effective_start_in_future(
        self, mock_get_cal, mock_tz, mock_localize, mock_to_utc
    ):
        from zoneinfo import ZoneInfo

        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_cal.return_value = ("cal-uuid-1", [])

        rule = ProviderAvailabilityRule(
            id="rule-1",
            provider_id=PROVIDER_ID,
            location_ids=[LOCATION_ID],
            weekly_schedule={
                "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
            },
            effective_start=date(2026, 4, 1),
            effective_end=date(2026, 4, 30),
        )

        with patch(f"{MODULE}.date") as mock_date:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

            result = _build_rule_events(rule)

        # First Monday on or after April 1 is April 6, before April 30
        assert len(result) == 1

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}._get_calendar_id")
    def test_effective_start_in_past_uses_today(
        self, mock_get_cal, mock_tz, mock_localize, mock_to_utc
    ):
        """When effective_start is before today, range_start should be today."""
        from zoneinfo import ZoneInfo

        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_cal.return_value = ("cal-uuid-1", [])

        rule = ProviderAvailabilityRule(
            id="rule-1",
            provider_id=PROVIDER_ID,
            location_ids=[LOCATION_ID],
            weekly_schedule={
                "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
            },
            effective_start=date(2025, 1, 1),  # in the past
            effective_end=date(2026, 3, 31),
        )

        with patch(f"{MODULE}.date") as mock_date, \
             patch(f"{MODULE}.EventEffect") as mock_event_effect:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            mock_event_effect.return_value.create.return_value = MagicMock()

            result = _build_rule_events(rule)

            # starts_at should use 2026-03-02 (today) as range_start
            init_call = mock_event_effect.call_args_list[0]
            starts_at = init_call.kwargs["starts_at"]
            # Monday 2026-03-02 is the first Monday on or after today
            assert starts_at.month == 3
            assert starts_at.day == 2

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}._get_calendar_id")
    def test_calendar_creation_effects_included(
        self, mock_get_cal, mock_tz, mock_localize, mock_to_utc
    ):
        from zoneinfo import ZoneInfo

        mock_tz.return_value = ZoneInfo("US/Eastern")
        cal_effect = MagicMock()
        mock_get_cal.return_value = ("cal-uuid-1", [cal_effect])

        rule = ProviderAvailabilityRule(
            id="rule-1",
            provider_id=PROVIDER_ID,
            location_ids=[LOCATION_ID],
            weekly_schedule={
                "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
            },
        )

        with patch(f"{MODULE}.date") as mock_date:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

            result = _build_rule_events(rule)

        # First effect should be the calendar creation effect
        assert result[0] is cal_effect
        assert len(result) == 2  # 1 cal effect + 1 event effect

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}._get_calendar_id")
    def test_visit_types_set_as_allowed_note_types(
        self, mock_get_cal, mock_tz, mock_localize, mock_to_utc
    ):
        """When visit_types is set, it should be passed as allowed_note_types."""
        from zoneinfo import ZoneInfo

        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_cal.return_value = ("cal-uuid-1", [])

        # Rule with visit_types
        rule = ProviderAvailabilityRule(
            id="rule-1",
            provider_id=PROVIDER_ID,
            location_ids=[LOCATION_ID],
            visit_types=["vt-1", "vt-2"],
            weekly_schedule={
                "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
            },
        )

        with patch(f"{MODULE}.date") as mock_date, \
             patch(f"{MODULE}.EventEffect") as mock_event_effect:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            mock_event_effect.return_value.create.return_value = MagicMock()

            _build_rule_events(rule)

            # Verify allowed_note_types was passed
            init_call = mock_event_effect.call_args_list[0]
            assert init_call.kwargs["allowed_note_types"] == ["vt-1", "vt-2"]

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}._get_calendar_id")
    def test_no_visit_types_passes_none(
        self, mock_get_cal, mock_tz, mock_localize, mock_to_utc
    ):
        """When visit_types is empty, allowed_note_types should be None."""
        from zoneinfo import ZoneInfo

        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_cal.return_value = ("cal-uuid-1", [])

        rule = ProviderAvailabilityRule(
            id="rule-1",
            provider_id=PROVIDER_ID,
            location_ids=[LOCATION_ID],
            visit_types=[],
            weekly_schedule={
                "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
            },
        )

        with patch(f"{MODULE}.date") as mock_date, \
             patch(f"{MODULE}.EventEffect") as mock_event_effect:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            mock_event_effect.return_value.create.return_value = MagicMock()

            _build_rule_events(rule)

            init_call = mock_event_effect.call_args_list[0]
            assert init_call.kwargs["allowed_note_types"] is None

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}._get_calendar_id")
    def test_invalid_day_name_skipped(
        self, mock_get_cal, mock_tz, mock_localize, mock_to_utc
    ):
        from zoneinfo import ZoneInfo

        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_cal.return_value = ("cal-uuid-1", [])

        rule = ProviderAvailabilityRule(
            id="rule-1",
            provider_id=PROVIDER_ID,
            location_ids=[LOCATION_ID],
            weekly_schedule={
                "invalidday": [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
            },
        )

        with patch(f"{MODULE}.date") as mock_date:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

            result = _build_rule_events(rule)

        # No events created for invalid day name
        assert result == []

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}._get_calendar_id")
    def test_leap_year_fallback(
        self, mock_get_cal, mock_tz, mock_localize, mock_to_utc
    ):
        """When today is Feb 29 (leap year) and no effective_end, the horizon
        calculation falls back to Feb 28 to avoid ValueError."""
        from zoneinfo import ZoneInfo

        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_cal.return_value = ("cal-uuid-1", [])

        rule = ProviderAvailabilityRule(
            id="rule-1",
            provider_id=PROVIDER_ID,
            location_ids=[LOCATION_ID],
            weekly_schedule={
                "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
            },
            # No effective_end -> use horizon
        )

        # 2028-02-29 is a leap year Tuesday
        with patch(f"{MODULE}.date") as mock_date:
            mock_date.today.return_value = date(2028, 2, 29)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

            result = _build_rule_events(rule)

        # Should not crash and should produce events
        assert len(result) >= 1

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}._get_calendar_id")
    def test_first_weekday_beyond_range_end_produces_no_events(
        self, mock_get_cal, mock_tz, mock_localize, mock_to_utc
    ):
        """When the first occurrence of a weekday is after range_end, skip it."""
        from zoneinfo import ZoneInfo

        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_cal.return_value = ("cal-uuid-1", [])

        rule = ProviderAvailabilityRule(
            id="rule-1",
            provider_id=PROVIDER_ID,
            location_ids=[LOCATION_ID],
            weekly_schedule={
                # Friday = weekday 4
                "friday": [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
            },
            effective_start=date(2026, 3, 2),  # Monday
            effective_end=date(2026, 3, 5),     # Thursday
        )

        with patch(f"{MODULE}.date") as mock_date:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

            result = _build_rule_events(rule)

        # Friday is after Thursday end, so no events
        assert result == []

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}._get_calendar_id")
    def test_multiple_windows_same_day(
        self, mock_get_cal, mock_tz, mock_localize, mock_to_utc
    ):
        """Multiple time windows on the same day produce multiple events."""
        from zoneinfo import ZoneInfo

        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_cal.return_value = ("cal-uuid-1", [])

        rule = ProviderAvailabilityRule(
            id="rule-1",
            provider_id=PROVIDER_ID,
            location_ids=[LOCATION_ID],
            weekly_schedule={
                "monday": [
                    TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0)),
                    TimeWindow(start=dt.time(13, 0), end=dt.time(17, 0)),
                ],
            },
        )

        with patch(f"{MODULE}.date") as mock_date:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

            result = _build_rule_events(rule)

        # 2 windows on Monday = 2 event effects
        assert len(result) == 2


# ── build_block_event_effects ─────────────────────────────────────────


class TestBuildBlockEventEffects:
    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    def test_creates_block_event(
        self, mock_get_admin_cal, mock_tz, mock_localize, mock_to_utc, sample_block
    ):
        from zoneinfo import ZoneInfo

        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_admin_cal.return_value = ("admin-cal-1", [])

        result = build_block_event_effects(sample_block)

        assert mock_get_admin_cal.mock_calls == [call(sample_block.provider_id, None)]
        assert len(result) == 1  # 1 event effect (no cal effects)

    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    def test_no_admin_calendar_returns_empty(
        self, mock_get_admin_cal, mock_tz, sample_block
    ):
        from zoneinfo import ZoneInfo

        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_admin_cal.return_value = ("", [])

        result = build_block_event_effects(sample_block)

        assert result == []

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    def test_uses_reason_as_title(
        self, mock_get_admin_cal, mock_tz, mock_localize, mock_to_utc
    ):
        from zoneinfo import ZoneInfo

        mock_tz.return_value = ZoneInfo("US/Eastern")
        cal_effect = MagicMock()
        mock_get_admin_cal.return_value = ("admin-cal-1", [cal_effect])

        block = AdminBlock(
            id="block-1",
            provider_id=PROVIDER_ID,
            start=datetime(2026, 3, 10, 9, 0),
            end=datetime(2026, 3, 10, 12, 0),
            reason="Conference",
        )

        with patch(f"{MODULE}.EventEffect") as mock_event_effect:
            mock_event_effect.return_value.create.return_value = MagicMock()
            result = build_block_event_effects(block)

            init_call = mock_event_effect.call_args_list[0]
            assert init_call.kwargs["title"] == "Conference"

        # Calendar creation effect + event effect
        assert len(result) == 2

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    def test_empty_reason_uses_blocked(
        self, mock_get_admin_cal, mock_tz, mock_localize, mock_to_utc
    ):
        from zoneinfo import ZoneInfo

        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_admin_cal.return_value = ("admin-cal-1", [])

        block = AdminBlock(
            id="block-1",
            provider_id=PROVIDER_ID,
            start=datetime(2026, 3, 10, 9, 0),
            end=datetime(2026, 3, 10, 12, 0),
            reason="",
        )

        with patch(f"{MODULE}.EventEffect") as mock_event_effect:
            mock_event_effect.return_value.create.return_value = MagicMock()
            build_block_event_effects(block)

            init_call = mock_event_effect.call_args_list[0]
            assert init_call.kwargs["title"] == "Blocked"

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    def test_aware_datetime_not_localized(
        self, mock_get_admin_cal, mock_tz, mock_to_utc
    ):
        """Timezone-aware datetimes should not be re-localized."""
        from zoneinfo import ZoneInfo

        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_admin_cal.return_value = ("admin-cal-1", [])

        aware_start = datetime(2026, 3, 10, 14, 0, tzinfo=UTC)
        aware_end = datetime(2026, 3, 10, 17, 0, tzinfo=UTC)

        block = AdminBlock(
            id="block-1",
            provider_id=PROVIDER_ID,
            start=aware_start,
            end=aware_end,
        )

        with patch(f"{MODULE}.EventEffect") as mock_event_effect, \
             patch(f"{MODULE}.localize_naive") as mock_localize:
            mock_event_effect.return_value.create.return_value = MagicMock()
            build_block_event_effects(block)

            # localize_naive should NOT be called for aware datetimes
            assert mock_localize.mock_calls == []

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    def test_includes_cal_effects(
        self, mock_get_admin_cal, mock_tz, mock_localize, mock_to_utc
    ):
        """Calendar creation effects should be included in the result."""
        from zoneinfo import ZoneInfo

        mock_tz.return_value = ZoneInfo("US/Eastern")
        cal_eff = MagicMock()
        mock_get_admin_cal.return_value = ("admin-cal-1", [cal_eff])

        block = AdminBlock(
            id="block-1",
            provider_id=PROVIDER_ID,
            start=datetime(2026, 3, 10, 9, 0),
            end=datetime(2026, 3, 10, 12, 0),
        )

        result = build_block_event_effects(block)

        assert result[0] is cal_eff
        assert len(result) == 2


# ── build_delete_block_effects ────────────────────────────────────────


class TestBuildDeleteBlockEffects:
    @patch(f"{MODULE}.get_event_ids")
    def test_stored_ids_used(self, mock_get_ids, sample_block):
        mock_get_ids.return_value = ["evt-1", "evt-2"]

        result = build_delete_block_effects(PROVIDER_ID, sample_block)

        assert mock_get_ids.mock_calls == [call(sample_block.id)]
        assert len(result) == 2

    @patch(f"{MODULE}.provider_tz", return_value=ZoneInfo("UTC"))
    @patch(f"{MODULE}.get_admin_calendars")
    @patch(f"{MODULE}.get_event_ids")
    def test_time_range_fallback(self, mock_get_ids, mock_get_admin_cals, mock_tz, sample_block):
        mock_get_ids.return_value = []

        mock_cal = MagicMock()
        mock_cal.id = "admin-cal-1"
        mock_get_admin_cals.return_value = [mock_cal]

        mock_evt = MagicMock()
        mock_evt.id = "evt-found-1"

        with patch(f"{MODULE}.EventModel.objects") as mock_event_objects:
            mock_event_objects.filter.return_value = [mock_evt]

            result = build_delete_block_effects(PROVIDER_ID, sample_block)

        assert mock_event_objects.filter.call_count >= 1
        first_call = mock_event_objects.filter.call_args_list[0]
        assert first_call.kwargs["calendar__id__in"] == ["admin-cal-1"]
        assert first_call.kwargs["is_cancelled"] is False
        assert len(result) == 1

    @patch(f"{MODULE}.get_admin_calendars")
    def test_no_block_deletes_all_block_titled(self, mock_get_admin_cals):
        mock_cal = MagicMock()
        mock_cal.id = "admin-cal-1"
        mock_get_admin_cals.return_value = [mock_cal]

        mock_evt = MagicMock()
        mock_evt.id = "evt-block-1"

        with patch(f"{MODULE}.EventModel.objects") as mock_event_objects:
            mock_event_objects.filter.return_value = [mock_evt]

            result = build_delete_block_effects(PROVIDER_ID, block=None)

        assert mock_event_objects.filter.call_args == call(
            calendar__id__in=["admin-cal-1"],
            title=BLOCK_TITLE,
            is_cancelled=False,
        )
        assert len(result) == 1

    @patch(f"{MODULE}.provider_tz", return_value=ZoneInfo("UTC"))
    @patch(f"{MODULE}.get_admin_calendars")
    @patch(f"{MODULE}.get_event_ids")
    def test_no_events_found_returns_empty(self, mock_get_ids, mock_get_admin_cals, mock_tz, sample_block):
        mock_get_ids.return_value = []
        mock_get_admin_cals.return_value = []

        result = build_delete_block_effects(PROVIDER_ID, sample_block)

        assert result == []

    @patch(f"{MODULE}.get_admin_calendars")
    def test_no_block_no_calendars_returns_empty(self, mock_get_admin_cals):
        mock_get_admin_cals.return_value = []

        result = build_delete_block_effects(PROVIDER_ID, block=None)

        assert result == []

    @patch(f"{MODULE}.provider_tz", return_value=ZoneInfo("UTC"))
    @patch(f"{MODULE}.get_admin_calendars")
    @patch(f"{MODULE}.get_event_ids")
    def test_time_range_fallback_multiple_calendars(
        self, mock_get_ids, mock_get_admin_cals, mock_tz, sample_block
    ):
        """When stored IDs are empty, searches across multiple admin calendars."""
        mock_get_ids.return_value = []

        mock_cal1 = MagicMock()
        mock_cal1.id = "admin-cal-1"
        mock_cal2 = MagicMock()
        mock_cal2.id = "admin-cal-2"
        mock_get_admin_cals.return_value = [mock_cal1, mock_cal2]

        mock_evt1 = MagicMock()
        mock_evt1.id = "evt-1"
        mock_evt2 = MagicMock()
        mock_evt2.id = "evt-2"

        with patch(f"{MODULE}.EventModel.objects") as mock_event_objects:
            mock_event_objects.filter.return_value = [mock_evt1, mock_evt2]

            result = build_delete_block_effects(PROVIDER_ID, sample_block)

        # One bulk query spanning both admin calendars
        assert len(result) == 2
        assert mock_event_objects.filter.call_count == 1
        assert mock_event_objects.filter.call_args.kwargs["calendar__id__in"] == [
            "admin-cal-1",
            "admin-cal-2",
        ]


# NOTE: delete_all_plugin_events() was removed (it destroyed non-plugin events
# on shared calendars). Reconciliation is now per-entity; see
# tests/protocols/test_staff_lifecycle.py for the non-destructive install path.


# ── delete_all_lead_time_events ───────────────────────────────────────


class TestDeleteAllLeadTimeEvents:
    def test_deletes_lead_time_events(self):
        mock_cal = MagicMock()
        mock_cal.id = "admin-cal-1"

        mock_evt = MagicMock()
        mock_evt.id = "lead-evt-1"

        with patch(f"{MODULE}.CalendarModel.objects") as mock_cal_objects, \
             patch(f"{MODULE}.EventModel.objects") as mock_event_objects:
            mock_cal_objects.filter.return_value = [mock_cal]
            mock_event_objects.filter.return_value = [mock_evt]

            result = delete_all_lead_time_events()

        assert len(result) == 1
        assert mock_cal_objects.mock_calls == [
            call.filter(title__contains=": Admin"),
        ]

    def test_no_admin_calendars_returns_empty(self):
        with patch(f"{MODULE}.CalendarModel.objects") as mock_cal_objects:
            mock_cal_objects.filter.return_value = []

            result = delete_all_lead_time_events()

        assert result == []

    def test_multiple_calendars_aggregates_deletions(self):
        mock_cal1 = MagicMock()
        mock_cal1.id = "admin-cal-1"
        mock_cal2 = MagicMock()
        mock_cal2.id = "admin-cal-2"

        mock_evt1 = MagicMock()
        mock_evt1.id = "lead-1"
        mock_evt2 = MagicMock()
        mock_evt2.id = "lead-2"

        with patch(f"{MODULE}.CalendarModel.objects") as mock_cal_objects, \
             patch(f"{MODULE}.EventModel.objects") as mock_event_objects:
            mock_cal_objects.filter.return_value = [mock_cal1, mock_cal2]
            mock_event_objects.filter.return_value = [mock_evt1, mock_evt2]

            result = delete_all_lead_time_events()

        # One bulk query spanning both admin calendars
        assert len(result) == 2
        assert mock_event_objects.filter.call_count == 1
        assert mock_event_objects.filter.call_args.kwargs["calendar__id__in"] == [
            "admin-cal-1",
            "admin-cal-2",
        ]

    def test_calendars_with_no_lead_events(self):
        mock_cal = MagicMock()
        mock_cal.id = "admin-cal-1"

        with patch(f"{MODULE}.CalendarModel.objects") as mock_cal_objects, \
             patch(f"{MODULE}.EventModel.objects") as mock_event_objects:
            mock_cal_objects.filter.return_value = [mock_cal]
            mock_event_objects.filter.return_value = []

            result = delete_all_lead_time_events()

        assert result == []


# ── build_recurring_block_sync_effects ────────────────────────────────


class TestBuildRecurringBlockSyncEffects:
    @pytest.fixture(autouse=True)
    def _mock_override_map(self):
        with patch(f"{MODULE}.get_rules_for_provider", return_value=[]):
            yield

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    @patch(f"{MODULE}.build_delete_recurring_block_effects")
    def test_creates_recurring_events(
        self, mock_delete, mock_get_admin_cal, mock_tz, mock_localize, mock_to_utc,
        sample_recurring_block,
    ):
        from zoneinfo import ZoneInfo

        mock_delete.return_value = []
        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_admin_cal.return_value = ("admin-cal-1", [])

        with patch(f"{MODULE}.date") as mock_date:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

            result = build_recurring_block_sync_effects(sample_recurring_block)

        assert mock_delete.mock_calls == [
            call(sample_recurring_block.provider_id, sample_recurring_block),
        ]
        # sample_recurring_block: friday 12-13 = 1 event
        assert len(result) == 1

    @patch(f"{MODULE}.build_delete_recurring_block_effects")
    def test_inactive_block_only_deletes(
        self, mock_delete, sample_recurring_block
    ):
        sample_recurring_block.is_active = False
        mock_delete.return_value = [MagicMock()]

        result = build_recurring_block_sync_effects(sample_recurring_block)

        assert mock_delete.mock_calls == [
            call(sample_recurring_block.provider_id, sample_recurring_block),
        ]
        # Only delete effects, no create effects
        assert len(result) == 1

    @patch(f"{MODULE}.build_delete_recurring_block_effects")
    def test_hold_type_skips_calendar_events(
        self, mock_delete, sample_recurring_block
    ):
        sample_recurring_block.hold_type = "soft"
        mock_delete.return_value = []

        result = build_recurring_block_sync_effects(sample_recurring_block)

        assert mock_delete.mock_calls == [
            call(sample_recurring_block.provider_id, sample_recurring_block),
        ]
        assert result == []

    @patch(f"{MODULE}.build_delete_recurring_block_effects")
    def test_hold_type_hard_skips_calendar_events(
        self, mock_delete, sample_recurring_block
    ):
        sample_recurring_block.hold_type = "hard"
        mock_delete.return_value = []

        result = build_recurring_block_sync_effects(sample_recurring_block)

        assert result == []

    @patch(f"{MODULE}.build_delete_recurring_block_effects")
    def test_no_weekly_schedule_only_deletes(self, mock_delete):
        block = RecurringBlock(
            id="rb-1",
            provider_id=PROVIDER_ID,
            weekly_schedule={},
            is_active=True,
        )
        del_eff = MagicMock()
        mock_delete.return_value = [del_eff]

        result = build_recurring_block_sync_effects(block)

        assert result == [del_eff]

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    @patch(f"{MODULE}.build_delete_recurring_block_effects")
    def test_no_admin_calendar_returns_delete_effects(
        self, mock_delete, mock_get_admin_cal, mock_tz, mock_localize, mock_to_utc,
        sample_recurring_block,
    ):
        from zoneinfo import ZoneInfo

        del_eff = MagicMock()
        mock_delete.return_value = [del_eff]
        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_admin_cal.return_value = ("", [])

        with patch(f"{MODULE}.date") as mock_date:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

            result = build_recurring_block_sync_effects(sample_recurring_block)

        # Only delete effects returned since no admin calendar
        assert result == [del_eff]

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    @patch(f"{MODULE}.build_delete_recurring_block_effects")
    def test_uses_reason_as_title(
        self, mock_delete, mock_get_admin_cal, mock_tz, mock_localize, mock_to_utc,
        sample_recurring_block,
    ):
        from zoneinfo import ZoneInfo

        mock_delete.return_value = []
        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_admin_cal.return_value = ("admin-cal-1", [])

        with patch(f"{MODULE}.date") as mock_date, \
             patch(f"{MODULE}.EventEffect") as mock_event_effect:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            mock_event_effect.return_value.create.return_value = MagicMock()

            build_recurring_block_sync_effects(sample_recurring_block)

            init_call = mock_event_effect.call_args_list[0]
            assert init_call.kwargs["title"] == "Lunch"

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    @patch(f"{MODULE}.build_delete_recurring_block_effects")
    def test_empty_reason_uses_blocked(
        self, mock_delete, mock_get_admin_cal, mock_tz, mock_localize, mock_to_utc
    ):
        from zoneinfo import ZoneInfo

        mock_delete.return_value = []
        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_admin_cal.return_value = ("admin-cal-1", [])

        block = RecurringBlock(
            id="rb-1",
            provider_id=PROVIDER_ID,
            weekly_schedule={
                "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(10, 0))],
            },
            reason="",
            is_active=True,
        )

        with patch(f"{MODULE}.date") as mock_date, \
             patch(f"{MODULE}.EventEffect") as mock_event_effect:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            mock_event_effect.return_value.create.return_value = MagicMock()

            build_recurring_block_sync_effects(block)

            init_call = mock_event_effect.call_args_list[0]
            assert init_call.kwargs["title"] == "Blocked"

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    @patch(f"{MODULE}.build_delete_recurring_block_effects")
    def test_effective_date_range(
        self, mock_delete, mock_get_admin_cal, mock_tz, mock_localize, mock_to_utc
    ):
        from zoneinfo import ZoneInfo

        mock_delete.return_value = []
        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_admin_cal.return_value = ("admin-cal-1", [])

        block = RecurringBlock(
            id="rb-1",
            provider_id=PROVIDER_ID,
            weekly_schedule={
                "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(10, 0))],
            },
            reason="Meeting",
            is_active=True,
            effective_start=date(2026, 4, 1),
            effective_end=date(2026, 4, 30),
        )

        with patch(f"{MODULE}.date") as mock_date, \
             patch(f"{MODULE}.EventEffect") as mock_event_effect:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            mock_event_effect.return_value.create.return_value = MagicMock()

            result = build_recurring_block_sync_effects(block)

            # First monday on or after April 1 is April 6 which is before April 30
            init_call = mock_event_effect.call_args_list[0]
            starts_at = init_call.kwargs["starts_at"]
            # The date portion should be April 6 (first Monday on or after April 1)
            assert starts_at.month == 4
            assert starts_at.day == 6

        assert len(result) == 1

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    @patch(f"{MODULE}.build_delete_recurring_block_effects")
    def test_calendar_effects_included(
        self, mock_delete, mock_get_admin_cal, mock_tz, mock_localize, mock_to_utc,
        sample_recurring_block,
    ):
        from zoneinfo import ZoneInfo

        mock_delete.return_value = []
        mock_tz.return_value = ZoneInfo("US/Eastern")
        cal_effect = MagicMock()
        mock_get_admin_cal.return_value = ("admin-cal-1", [cal_effect])

        with patch(f"{MODULE}.date") as mock_date:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

            result = build_recurring_block_sync_effects(sample_recurring_block)

        # cal_effect + 1 event (friday 12-13)
        assert result[0] is cal_effect
        assert len(result) == 2

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    @patch(f"{MODULE}.build_delete_recurring_block_effects")
    def test_leap_year_fallback_recurring(
        self, mock_delete, mock_get_admin_cal, mock_tz, mock_localize, mock_to_utc
    ):
        """Feb 29 leap year without effective_end uses day-1 fallback."""
        from zoneinfo import ZoneInfo

        mock_delete.return_value = []
        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_admin_cal.return_value = ("admin-cal-1", [])

        block = RecurringBlock(
            id="rb-1",
            provider_id=PROVIDER_ID,
            weekly_schedule={
                "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(10, 0))],
            },
            is_active=True,
        )

        with patch(f"{MODULE}.date") as mock_date:
            mock_date.today.return_value = date(2028, 2, 29)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

            result = build_recurring_block_sync_effects(block)

        # Should not crash
        assert len(result) >= 1

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    @patch(f"{MODULE}.build_delete_recurring_block_effects")
    def test_invalid_day_skipped(
        self, mock_delete, mock_get_admin_cal, mock_tz, mock_localize, mock_to_utc
    ):
        from zoneinfo import ZoneInfo

        mock_delete.return_value = []
        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_admin_cal.return_value = ("admin-cal-1", [])

        block = RecurringBlock(
            id="rb-1",
            provider_id=PROVIDER_ID,
            weekly_schedule={
                "badday": [TimeWindow(start=dt.time(9, 0), end=dt.time(10, 0))],
            },
            is_active=True,
        )

        with patch(f"{MODULE}.date") as mock_date:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

            result = build_recurring_block_sync_effects(block)

        assert result == []


# ── build_delete_recurring_block_effects ──────────────────────────────


class TestBuildDeleteRecurringBlockEffects:
    @patch(f"{MODULE}.get_event_ids")
    def test_stored_ids_used(self, mock_get_ids, sample_recurring_block):
        mock_get_ids.return_value = ["evt-1", "evt-2", "evt-3"]

        result = build_delete_recurring_block_effects(
            PROVIDER_ID, sample_recurring_block
        )

        assert mock_get_ids.mock_calls == [call(sample_recurring_block.id)]
        assert len(result) == 3

    @patch(f"{MODULE}.get_admin_calendars")
    @patch(f"{MODULE}.get_event_ids")
    def test_fallback_to_title_match(
        self, mock_get_ids, mock_get_admin_cals, sample_recurring_block
    ):
        mock_get_ids.return_value = []

        mock_cal = MagicMock()
        mock_cal.id = "admin-cal-1"
        mock_get_admin_cals.return_value = [mock_cal]

        mock_evt = MagicMock()
        mock_evt.id = "evt-found-1"

        with patch(f"{MODULE}.EventModel.objects") as mock_event_objects:
            mock_event_objects.filter.return_value = [mock_evt]

            result = build_delete_recurring_block_effects(
                PROVIDER_ID, sample_recurring_block
            )

        # Should match by block's reason ("Lunch") AND legacy RECURRING_BLOCK_TITLE
        assert mock_event_objects.filter.call_args == call(
            calendar__id__in=["admin-cal-1"],
            title__in=["Lunch", RECURRING_BLOCK_TITLE],
            is_cancelled=False,
        )
        assert len(result) == 1

    @patch(f"{MODULE}.get_admin_calendars")
    def test_no_block_uses_legacy_title(self, mock_get_admin_cals):
        mock_cal = MagicMock()
        mock_cal.id = "admin-cal-1"
        mock_get_admin_cals.return_value = [mock_cal]

        mock_evt = MagicMock()
        mock_evt.id = "evt-1"

        with patch(f"{MODULE}.EventModel.objects") as mock_event_objects:
            mock_event_objects.filter.return_value = [mock_evt]

            result = build_delete_recurring_block_effects(PROVIDER_ID, block=None)

        assert mock_event_objects.filter.call_args == call(
            calendar__id__in=["admin-cal-1"],
            title=RECURRING_BLOCK_TITLE,
            is_cancelled=False,
        )
        assert len(result) == 1

    @patch(f"{MODULE}.get_admin_calendars")
    @patch(f"{MODULE}.get_event_ids")
    def test_no_events_returns_empty(
        self, mock_get_ids, mock_get_admin_cals, sample_recurring_block
    ):
        mock_get_ids.return_value = []
        mock_get_admin_cals.return_value = []

        result = build_delete_recurring_block_effects(
            PROVIDER_ID, sample_recurring_block
        )

        assert result == []

    @patch(f"{MODULE}.get_admin_calendars")
    @patch(f"{MODULE}.get_event_ids")
    def test_fallback_block_with_empty_reason(
        self, mock_get_ids, mock_get_admin_cals
    ):
        """Block with empty reason uses 'Blocked' as title to match."""
        mock_get_ids.return_value = []
        mock_get_admin_cals.return_value = []

        block = RecurringBlock(
            id="rb-1",
            provider_id=PROVIDER_ID,
            weekly_schedule={},
            reason="",
            is_active=True,
        )

        result = build_delete_recurring_block_effects(PROVIDER_ID, block)

        assert result == []

    @patch(f"{MODULE}.get_admin_calendars")
    @patch(f"{MODULE}.get_event_ids")
    def test_fallback_block_with_empty_reason_searches_blocked_and_legacy(
        self, mock_get_ids, mock_get_admin_cals
    ):
        """Block with empty reason searches for both 'Blocked' and RECURRING_BLOCK_TITLE."""
        mock_get_ids.return_value = []

        mock_cal = MagicMock()
        mock_cal.id = "admin-cal-1"
        mock_get_admin_cals.return_value = [mock_cal]

        mock_evt = MagicMock()
        mock_evt.id = "evt-1"

        block = RecurringBlock(
            id="rb-1",
            provider_id=PROVIDER_ID,
            reason="",
            is_active=True,
        )

        with patch(f"{MODULE}.EventModel.objects") as mock_event_objects:
            mock_event_objects.filter.return_value = [mock_evt]

            result = build_delete_recurring_block_effects(PROVIDER_ID, block)

        # "Blocked" != RECURRING_BLOCK_TITLE so both should be in the list
        assert mock_event_objects.filter.call_args == call(
            calendar__id__in=["admin-cal-1"],
            title__in=["Blocked", RECURRING_BLOCK_TITLE],
            is_cancelled=False,
        )
        assert len(result) == 1

    @patch(f"{MODULE}.get_admin_calendars")
    def test_no_block_no_calendars(self, mock_get_admin_cals):
        mock_get_admin_cals.return_value = []

        result = build_delete_recurring_block_effects(PROVIDER_ID, block=None)

        assert result == []

    @patch(f"{MODULE}.get_admin_calendars")
    @patch(f"{MODULE}.get_event_ids")
    def test_fallback_multiple_calendars(
        self, mock_get_ids, mock_get_admin_cals, sample_recurring_block
    ):
        """Fallback title-match searches across all admin calendars."""
        mock_get_ids.return_value = []

        mock_cal1 = MagicMock()
        mock_cal1.id = "cal-1"
        mock_cal2 = MagicMock()
        mock_cal2.id = "cal-2"
        mock_get_admin_cals.return_value = [mock_cal1, mock_cal2]

        mock_evt1 = MagicMock()
        mock_evt1.id = "evt-1"
        mock_evt2 = MagicMock()
        mock_evt2.id = "evt-2"

        with patch(f"{MODULE}.EventModel.objects") as mock_event_objects:
            mock_event_objects.filter.return_value = [mock_evt1, mock_evt2]

            result = build_delete_recurring_block_effects(
                PROVIDER_ID, sample_recurring_block
            )

        # One bulk query spanning both admin calendars
        assert len(result) == 2
        assert mock_event_objects.filter.call_count == 1
        assert mock_event_objects.filter.call_args.kwargs["calendar__id__in"] == [
            "cal-1",
            "cal-2",
        ]


# ── build_lead_time_block_effects ─────────────────────────────────────


class TestBuildLeadTimeBlockEffects:
    def test_zero_lead_returns_empty(self):
        rule = ProviderAvailabilityRule(
            id="rule-1",
            provider_id=PROVIDER_ID,
            booking_interval=BookingInterval(min_lead_hours=0),
            weekly_schedule={
                "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(17, 0))],
            },
        )

        result = build_lead_time_block_effects(rule)

        assert result == []

    def test_negative_lead_returns_empty(self):
        rule = ProviderAvailabilityRule(
            id="rule-1",
            provider_id=PROVIDER_ID,
            booking_interval=BookingInterval(min_lead_hours=-1),
            weekly_schedule={
                "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(17, 0))],
            },
        )

        result = build_lead_time_block_effects(rule)

        assert result == []

    @patch(f"{MODULE}.get_admin_calendar_id")
    def test_no_admin_calendar_returns_empty(self, mock_get_admin_cal):
        mock_get_admin_cal.return_value = ("", [])

        rule = ProviderAvailabilityRule(
            id="rule-1",
            provider_id=PROVIDER_ID,
            booking_interval=BookingInterval(min_lead_hours=24),
            weekly_schedule={
                "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(17, 0))],
            },
        )

        result = build_lead_time_block_effects(rule)

        assert result == []

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.get_admin_calendars")
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    def test_creates_lead_time_blocks_during_working_hours(
        self, mock_get_admin_cal, mock_tz, mock_get_admin_cals, mock_to_utc
    ):
        from zoneinfo import ZoneInfo

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
        )

        # Simulate a Monday at 10:00 AM Eastern
        mock_now = datetime(2026, 3, 2, 10, 0, tzinfo=tz)
        with patch(f"{MODULE}.datetime") as mock_datetime:
            mock_datetime.now.return_value = mock_now
            mock_datetime.combine = datetime.combine
            mock_datetime.side_effect = lambda *a, **kw: datetime(*a, **kw)

            result = build_lead_time_block_effects(rule)

        # Should create a lead-time block from 10:00 to 14:00 (4h lead)
        # intersected with 9:00-17:00 working hours = 10:00-14:00
        assert len(result) == 1  # 1 event create effect

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.get_admin_calendars")
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    def test_skips_rebuild_within_drift_threshold(
        self, mock_get_admin_cal, mock_tz, mock_get_admin_cals, mock_to_utc
    ):
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("US/Eastern")
        mock_tz.return_value = tz
        mock_get_admin_cal.return_value = ("admin-cal-1", [])

        rule = ProviderAvailabilityRule(
            id="rule-1",
            provider_id=PROVIDER_ID,
            booking_interval=BookingInterval(min_lead_hours=4),
            weekly_schedule={
                "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(17, 0))],
            },
        )

        mock_now = datetime(2026, 3, 2, 10, 0, tzinfo=tz)

        # Create an existing event whose starts_at/ends_at are within 1 min
        # of the expected window (well within the 5-min threshold).
        # The key is that to_utc is identity, so the "expected" UTC values
        # are the Eastern TZ-aware datetimes themselves. The existing event
        # must use the same TZ-aware representation for the comparison to work.
        existing_evt = MagicMock()
        existing_evt.starts_at = datetime(2026, 3, 2, 10, 1, tzinfo=tz)  # 1 min drift
        existing_evt.ends_at = datetime(2026, 3, 2, 14, 1, tzinfo=tz)    # 1 min drift

        mock_cal = MagicMock()
        mock_cal.id = "admin-cal-1"
        mock_get_admin_cals.return_value = [mock_cal]

        with patch(f"{MODULE}.datetime") as mock_datetime, \
             patch(f"{MODULE}.EventModel.objects") as mock_event_objects:
            mock_datetime.now.return_value = mock_now
            mock_datetime.combine = datetime.combine
            mock_datetime.side_effect = lambda *a, **kw: datetime(*a, **kw)

            mock_qs = MagicMock()
            mock_qs.order_by.return_value = [existing_evt]
            mock_event_objects.filter.return_value = mock_qs

            result = build_lead_time_block_effects(rule)

        # Should skip rebuild since drift is within threshold (< 300 seconds)
        # Returns only cal_effects (empty list)
        assert result == []

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.get_admin_calendars")
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    def test_rebuilds_when_drifted_beyond_threshold(
        self, mock_get_admin_cal, mock_tz, mock_get_admin_cals, mock_to_utc
    ):
        """When existing events have drifted beyond the threshold, rebuild."""
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("US/Eastern")
        mock_tz.return_value = tz
        mock_get_admin_cal.return_value = ("admin-cal-1", [])

        rule = ProviderAvailabilityRule(
            id="rule-1",
            provider_id=PROVIDER_ID,
            booking_interval=BookingInterval(min_lead_hours=4),
            weekly_schedule={
                "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(17, 0))],
            },
        )

        mock_now = datetime(2026, 3, 2, 10, 0, tzinfo=tz)

        # Existing event drifted by 10 minutes = 600 seconds (> 300 threshold)
        existing_evt = MagicMock()
        existing_evt.id = "old-evt"
        existing_evt.starts_at = datetime(2026, 3, 2, 9, 50, tzinfo=tz)   # 10 min drift
        existing_evt.ends_at = datetime(2026, 3, 2, 13, 50, tzinfo=tz)    # 10 min drift

        mock_cal = MagicMock()
        mock_cal.id = "admin-cal-1"
        mock_get_admin_cals.return_value = [mock_cal]

        with patch(f"{MODULE}.datetime") as mock_datetime, \
             patch(f"{MODULE}.EventModel.objects") as mock_event_objects:
            mock_datetime.now.return_value = mock_now
            mock_datetime.combine = datetime.combine
            mock_datetime.side_effect = lambda *a, **kw: datetime(*a, **kw)

            mock_qs = MagicMock()
            mock_qs.order_by.return_value = [existing_evt]
            mock_event_objects.filter.return_value = mock_qs

            result = build_lead_time_block_effects(rule)

        # Should rebuild: 1 delete + 1 create = 2 effects
        assert len(result) == 2

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.get_admin_calendars")
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    def test_rebuilds_when_interval_count_mismatch(
        self, mock_get_admin_cal, mock_tz, mock_get_admin_cals, mock_to_utc
    ):
        """When existing event count differs from expected intervals, rebuild."""
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("US/Eastern")
        mock_tz.return_value = tz
        mock_get_admin_cal.return_value = ("admin-cal-1", [])

        rule = ProviderAvailabilityRule(
            id="rule-1",
            provider_id=PROVIDER_ID,
            booking_interval=BookingInterval(min_lead_hours=4),
            weekly_schedule={
                "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(17, 0))],
            },
        )

        mock_now = datetime(2026, 3, 2, 10, 0, tzinfo=tz)

        # Two existing events but only one expected interval
        existing_evt1 = MagicMock()
        existing_evt1.id = "old-1"
        existing_evt1.starts_at = datetime(2026, 3, 2, 10, 0, tzinfo=tz)
        existing_evt1.ends_at = datetime(2026, 3, 2, 12, 0, tzinfo=tz)
        existing_evt2 = MagicMock()
        existing_evt2.id = "old-2"
        existing_evt2.starts_at = datetime(2026, 3, 2, 12, 0, tzinfo=tz)
        existing_evt2.ends_at = datetime(2026, 3, 2, 14, 0, tzinfo=tz)

        mock_cal = MagicMock()
        mock_cal.id = "admin-cal-1"
        mock_get_admin_cals.return_value = [mock_cal]

        with patch(f"{MODULE}.datetime") as mock_datetime, \
             patch(f"{MODULE}.EventModel.objects") as mock_event_objects:
            mock_datetime.now.return_value = mock_now
            mock_datetime.combine = datetime.combine
            mock_datetime.side_effect = lambda *a, **kw: datetime(*a, **kw)

            mock_qs = MagicMock()
            mock_qs.order_by.return_value = [existing_evt1, existing_evt2]
            mock_event_objects.filter.return_value = mock_qs

            result = build_lead_time_block_effects(rule)

        # Count mismatch (2 existing vs 1 interval) triggers rebuild
        # 2 deletes + 1 create = 3 effects
        assert len(result) == 3

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.get_admin_calendars")
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    def test_no_overlap_still_cleans_existing(
        self, mock_get_admin_cal, mock_tz, mock_get_admin_cals, mock_to_utc
    ):
        """When lead-time window doesn't overlap working hours,
        existing lead-time events should still be cleaned up."""
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("US/Eastern")
        mock_tz.return_value = tz
        mock_get_admin_cal.return_value = ("admin-cal-1", [])

        rule = ProviderAvailabilityRule(
            id="rule-1",
            provider_id=PROVIDER_ID,
            booking_interval=BookingInterval(min_lead_hours=2),
            weekly_schedule={
                # Only Tuesday availability, but it's Monday
                "tuesday": [TimeWindow(start=dt.time(9, 0), end=dt.time(17, 0))],
            },
        )

        mock_now = datetime(2026, 3, 2, 20, 0, tzinfo=tz)  # Monday 8 PM

        existing_evt = MagicMock()
        existing_evt.id = "old-lead-evt"

        mock_cal = MagicMock()
        mock_cal.id = "admin-cal-1"
        mock_get_admin_cals.return_value = [mock_cal]

        with patch(f"{MODULE}.datetime") as mock_datetime, \
             patch(f"{MODULE}.EventModel.objects") as mock_event_objects:
            mock_datetime.now.return_value = mock_now
            mock_datetime.combine = datetime.combine
            mock_datetime.side_effect = lambda *a, **kw: datetime(*a, **kw)

            mock_qs = MagicMock()
            mock_qs.order_by.return_value = [existing_evt]
            mock_event_objects.filter.return_value = mock_qs

            result = build_lead_time_block_effects(rule)

        # Should delete the existing lead-time event (cleanup)
        assert len(result) == 1  # 1 delete effect

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.get_admin_calendars")
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    def test_naive_existing_events_get_utc_tzinfo(
        self, mock_get_admin_cal, mock_tz, mock_get_admin_cals, mock_to_utc
    ):
        """Existing events with naive starts_at/ends_at get UTC tzinfo assigned."""
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("US/Eastern")
        mock_tz.return_value = tz
        mock_get_admin_cal.return_value = ("admin-cal-1", [])

        rule = ProviderAvailabilityRule(
            id="rule-1",
            provider_id=PROVIDER_ID,
            booking_interval=BookingInterval(min_lead_hours=4),
            weekly_schedule={
                "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(17, 0))],
            },
        )

        mock_now = datetime(2026, 3, 2, 10, 0, tzinfo=tz)

        # Naive datetimes (no tzinfo) -- code should replace with UTC
        existing_evt = MagicMock()
        existing_evt.id = "old-evt"
        existing_evt.starts_at = datetime(2026, 3, 2, 10, 1)  # naive, 1 min drift
        existing_evt.ends_at = datetime(2026, 3, 2, 14, 1)    # naive, 1 min drift

        mock_cal = MagicMock()
        mock_cal.id = "admin-cal-1"
        mock_get_admin_cals.return_value = [mock_cal]

        with patch(f"{MODULE}.datetime") as mock_datetime, \
             patch(f"{MODULE}.EventModel.objects") as mock_event_objects:
            mock_datetime.now.return_value = mock_now
            mock_datetime.combine = datetime.combine
            mock_datetime.side_effect = lambda *a, **kw: datetime(*a, **kw)

            mock_qs = MagicMock()
            mock_qs.order_by.return_value = [existing_evt]
            mock_event_objects.filter.return_value = mock_qs

            # This should not crash even with naive datetimes
            result = build_lead_time_block_effects(rule)

        # The function should handle naive datetimes without crashing.
        # Whether it skips or rebuilds depends on the TZ math, but no exception.
        assert isinstance(result, list)

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.get_admin_calendars")
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    def test_no_existing_events_creates_new(
        self, mock_get_admin_cal, mock_tz, mock_get_admin_cals, mock_to_utc
    ):
        """When no existing lead-time events, creates new ones."""
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("US/Eastern")
        mock_tz.return_value = tz
        mock_get_admin_cal.return_value = ("admin-cal-1", [])
        mock_get_admin_cals.return_value = []

        rule = ProviderAvailabilityRule(
            id="rule-1",
            provider_id=PROVIDER_ID,
            booking_interval=BookingInterval(min_lead_hours=2),
            weekly_schedule={
                "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(17, 0))],
            },
        )

        mock_now = datetime(2026, 3, 2, 10, 0, tzinfo=tz)  # Monday 10 AM

        with patch(f"{MODULE}.datetime") as mock_datetime:
            mock_datetime.now.return_value = mock_now
            mock_datetime.combine = datetime.combine
            mock_datetime.side_effect = lambda *a, **kw: datetime(*a, **kw)

            result = build_lead_time_block_effects(rule)

        # Should create 1 block: 10:00-12:00 (intersect [10, 12] with [9, 17])
        assert len(result) == 1

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.get_admin_calendars")
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    def test_multi_day_lead_time(
        self, mock_get_admin_cal, mock_tz, mock_get_admin_cals, mock_to_utc
    ):
        """Lead time spanning multiple days creates blocks on each working day."""
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("US/Eastern")
        mock_tz.return_value = tz
        mock_get_admin_cal.return_value = ("admin-cal-1", [])
        mock_get_admin_cals.return_value = []

        rule = ProviderAvailabilityRule(
            id="rule-1",
            provider_id=PROVIDER_ID,
            booking_interval=BookingInterval(min_lead_hours=30),  # spans to next day
            weekly_schedule={
                "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(17, 0))],
                "tuesday": [TimeWindow(start=dt.time(9, 0), end=dt.time(17, 0))],
            },
        )

        # Monday 10 AM, lead ends Tuesday 4 PM
        mock_now = datetime(2026, 3, 2, 10, 0, tzinfo=tz)

        with patch(f"{MODULE}.datetime") as mock_datetime:
            mock_datetime.now.return_value = mock_now
            mock_datetime.combine = datetime.combine
            mock_datetime.side_effect = lambda *a, **kw: datetime(*a, **kw)

            result = build_lead_time_block_effects(rule)

        # Monday 10:00-17:00 + Tuesday 9:00-16:00 = 2 blocks
        assert len(result) == 2

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.get_admin_calendars")
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    def test_includes_cal_effects(
        self, mock_get_admin_cal, mock_tz, mock_get_admin_cals, mock_to_utc
    ):
        """Calendar creation effects from get_admin_calendar_id are included."""
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("US/Eastern")
        mock_tz.return_value = tz
        cal_eff = MagicMock()
        mock_get_admin_cal.return_value = ("admin-cal-1", [cal_eff])
        mock_get_admin_cals.return_value = []

        rule = ProviderAvailabilityRule(
            id="rule-1",
            provider_id=PROVIDER_ID,
            booking_interval=BookingInterval(min_lead_hours=4),
            weekly_schedule={
                "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(17, 0))],
            },
        )

        mock_now = datetime(2026, 3, 2, 10, 0, tzinfo=tz)
        with patch(f"{MODULE}.datetime") as mock_datetime:
            mock_datetime.now.return_value = mock_now
            mock_datetime.combine = datetime.combine
            mock_datetime.side_effect = lambda *a, **kw: datetime(*a, **kw)

            result = build_lead_time_block_effects(rule)

        assert result[0] is cal_eff
        # cal_eff + 1 create = 2
        assert len(result) == 2

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.get_admin_calendars")
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    def test_no_working_hours_in_lead_window_no_events(
        self, mock_get_admin_cal, mock_tz, mock_get_admin_cals, mock_to_utc
    ):
        """When lead-time window doesn't intersect any working hours and no existing events."""
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("US/Eastern")
        mock_tz.return_value = tz
        mock_get_admin_cal.return_value = ("admin-cal-1", [])
        mock_get_admin_cals.return_value = []

        rule = ProviderAvailabilityRule(
            id="rule-1",
            provider_id=PROVIDER_ID,
            booking_interval=BookingInterval(min_lead_hours=2),
            weekly_schedule={
                # Only Wednesday, but today is Monday
                "wednesday": [TimeWindow(start=dt.time(9, 0), end=dt.time(17, 0))],
            },
        )

        mock_now = datetime(2026, 3, 2, 10, 0, tzinfo=tz)  # Monday 10 AM
        with patch(f"{MODULE}.datetime") as mock_datetime:
            mock_datetime.now.return_value = mock_now
            mock_datetime.combine = datetime.combine
            mock_datetime.side_effect = lambda *a, **kw: datetime(*a, **kw)

            result = build_lead_time_block_effects(rule)

        # No overlap, no existing events -> empty
        assert result == []


# ── Override event sync ──────────────────────────────────────────────────


class TestOverrideEventSync:
    """Tests for recurring-split override behavior in _build_rule_events."""

    def _make_rule(
        self,
        overrides: list[DateOverride] | None = None,
    ) -> ProviderAvailabilityRule:
        return ProviderAvailabilityRule(
            id="rule-1",
            provider_id=PROVIDER_ID,
            location_ids=[LOCATION_ID],
            weekly_schedule={
                "thursday": [TimeWindow(start=dt.time(9, 0), end=dt.time(15, 0))],
            },
            date_overrides=overrides or [],
            is_active=True,
        )

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda dt_val, tz: dt_val)
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}._get_calendar_id", return_value=("clinic-cal-1", []))
    def test_no_overrides_unchanged(
        self, mock_get_cal, mock_tz, mock_localize, mock_utc
    ):
        """A rule with no overrides produces a single recurring event (unchanged behavior)."""
        from zoneinfo import ZoneInfo
        mock_tz.return_value = ZoneInfo("US/Eastern")

        rule = self._make_rule()

        with patch(f"{MODULE}.date") as mock_date:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            effects = _build_rule_events(rule)

        # Single recurring event for Thursday
        assert len(effects) == 1

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda dt_val, tz: dt_val)
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}._get_calendar_id", return_value=("clinic-cal-1", []))
    def test_override_splits_recurring(
        self, mock_get_cal, mock_tz, mock_localize, mock_utc
    ):
        """A single override splits the recurring event into 2 segments + 1 one-off."""
        from zoneinfo import ZoneInfo
        mock_tz.return_value = ZoneInfo("US/Eastern")

        # Override on Thu 2026-04-09 with modified hours
        override = DateOverride(
            date=date(2026, 4, 9),
            time_windows=[TimeWindow(start=dt.time(8, 0), end=dt.time(12, 0))],
        )
        rule = self._make_rule(overrides=[override])

        with patch(f"{MODULE}.date") as mock_date:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            effects = _build_rule_events(rule)

        # 2 recurring segments (before + after override) + 1 one-off override event
        assert len(effects) == 3

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda dt_val, tz: dt_val)
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}._get_calendar_id", return_value=("clinic-cal-1", []))
    def test_closed_override_no_oneoff(
        self, mock_get_cal, mock_tz, mock_localize, mock_utc
    ):
        """A closed override splits the recurrence but creates no one-off event."""
        from zoneinfo import ZoneInfo
        mock_tz.return_value = ZoneInfo("US/Eastern")

        override = DateOverride(
            date=date(2026, 4, 9),
            is_closed=True,
        )
        rule = self._make_rule(overrides=[override])

        with patch(f"{MODULE}.date") as mock_date:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            effects = _build_rule_events(rule)

        # 2 recurring segments only, no one-off
        assert len(effects) == 2

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda dt_val, tz: dt_val)
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}._get_calendar_id", return_value=("clinic-cal-1", []))
    def test_multiple_overrides_same_weekday(
        self, mock_get_cal, mock_tz, mock_localize, mock_utc
    ):
        """Two overrides on the same weekday produce 3 segments + 2 one-off events."""
        from zoneinfo import ZoneInfo
        mock_tz.return_value = ZoneInfo("US/Eastern")

        overrides = [
            DateOverride(
                date=date(2026, 4, 9),
                time_windows=[TimeWindow(start=dt.time(8, 0), end=dt.time(12, 0))],
            ),
            DateOverride(
                date=date(2026, 5, 7),
                time_windows=[TimeWindow(start=dt.time(10, 0), end=dt.time(14, 0))],
            ),
        ]
        rule = self._make_rule(overrides=overrides)

        with patch(f"{MODULE}.date") as mock_date:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            effects = _build_rule_events(rule)

        # 3 recurring segments + 2 one-off override events = 5
        assert len(effects) == 5


class TestComputeRecurringSegments:
    """Tests for _compute_recurring_segments helper."""

    def test_no_overrides(self):
        """No override dates returns the full range as a single segment."""
        segments = _compute_recurring_segments(date(2026, 3, 5), date(2051, 3, 5), [])
        assert segments == [(date(2026, 3, 5), date(2051, 3, 5))]

    def test_single_override_middle(self):
        """An override in the middle produces two segments."""
        segments = _compute_recurring_segments(
            date(2026, 3, 5), date(2026, 5, 28),
            [date(2026, 4, 9)],
        )
        assert segments == [
            (date(2026, 3, 5), date(2026, 4, 2)),   # ends week before override
            (date(2026, 4, 16), date(2026, 5, 28)),  # starts week after override
        ]

    def test_override_on_first_date(self):
        """Override on the very first occurrence skips it, starts one week later."""
        segments = _compute_recurring_segments(
            date(2026, 3, 5), date(2026, 4, 30),
            [date(2026, 3, 5)],
        )
        # seg_end = 3/5 - 7 = 2/26 < 3/5, so no first segment
        # current_start = 3/12
        assert segments == [(date(2026, 3, 12), date(2026, 4, 30))]

    def test_override_on_last_date(self):
        """Override on the last possible occurrence."""
        segments = _compute_recurring_segments(
            date(2026, 3, 5), date(2026, 3, 19),
            [date(2026, 3, 19)],
        )
        # seg before: 3/5 to 3/12
        # after: 3/26 > 3/19, no second segment
        assert segments == [(date(2026, 3, 5), date(2026, 3, 12))]

    def test_consecutive_overrides(self):
        """Two consecutive weekly overrides — no segment between them."""
        segments = _compute_recurring_segments(
            date(2026, 3, 5), date(2026, 4, 30),
            [date(2026, 3, 19), date(2026, 3, 26)],
        )
        # Before first: 3/5 to 3/12
        # Between: 3/26+7=4/2 but 3/26-7=3/19 — no gap (3/26 is also an override)
        # After second: 4/2 to 4/30
        assert segments == [
            (date(2026, 3, 5), date(2026, 3, 12)),
            (date(2026, 4, 2), date(2026, 4, 30)),
        ]


# ── _build_rule_events: daily recurrence path ─────────────────────────


class TestBuildRuleEventsDaily:
    """Cover the daily-recurrence branch of _build_rule_events."""

    def test_daily_no_time_windows_returns_empty(self):
        rule = ProviderAvailabilityRule(
            id="rule-daily",
            provider_id=PROVIDER_ID,
            recurrence_frequency="daily",
            time_windows=[],
        )
        assert _build_rule_events(rule) == []

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}._get_calendar_id")
    def test_daily_creates_one_recurring_event_per_window(
        self, mock_get_cal, mock_tz, mock_localize, mock_to_utc
    ):
        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_cal.return_value = ("cal-1", [])
        rule = ProviderAvailabilityRule(
            id="rule-daily",
            provider_id=PROVIDER_ID,
            location_ids=[LOCATION_ID],
            recurrence_frequency="daily",
            time_windows=[
                TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0)),
                TimeWindow(start=dt.time(13, 0), end=dt.time(17, 0)),
            ],
        )
        with patch(f"{MODULE}.date") as mock_date, \
             patch(f"{MODULE}.EventEffect") as mock_ee:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            result = _build_rule_events(rule)

        # 2 windows x 1 location = 2 daily recurring events
        assert len(result) == 2
        kwargs = [c.kwargs for c in mock_ee.call_args_list]
        assert all(k["recurrence_frequency"] == EventRecurrence.Daily for k in kwargs)

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}._get_calendar_id")
    def test_daily_anchor_advances_off_interval(
        self, mock_get_cal, mock_tz, mock_localize, mock_to_utc
    ):
        """effective_start in the past, not on an interval boundary → anchor advances."""
        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_cal.return_value = ("cal-1", [])
        rule = ProviderAvailabilityRule(
            id="rule-daily",
            provider_id=PROVIDER_ID,
            location_ids=[LOCATION_ID],
            recurrence_frequency="daily",
            recurrence_interval=7,
            effective_start=date(2026, 2, 1),  # 29 days before today; 29 % 7 == 1
            time_windows=[TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
        )
        with patch(f"{MODULE}.date") as mock_date, \
             patch(f"{MODULE}.EventEffect") as mock_ee:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            result = _build_rule_events(rule)

        assert len(result) == 1
        # anchor = 2026-03-02 + (7 - 1) days = 2026-03-08
        assert mock_ee.call_args_list[0].kwargs["starts_at"].date() == date(2026, 3, 8)

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}._get_calendar_id")
    def test_daily_anchor_on_interval_boundary(
        self, mock_get_cal, mock_tz, mock_localize, mock_to_utc
    ):
        """effective_start in the past, exactly on an interval boundary → anchor = today."""
        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_cal.return_value = ("cal-1", [])
        rule = ProviderAvailabilityRule(
            id="rule-daily",
            provider_id=PROVIDER_ID,
            location_ids=[LOCATION_ID],
            recurrence_frequency="daily",
            recurrence_interval=7,
            effective_start=date(2026, 2, 23),  # 7 days before today; 7 % 7 == 0
            time_windows=[TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
        )
        with patch(f"{MODULE}.date") as mock_date, \
             patch(f"{MODULE}.EventEffect") as mock_ee:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            result = _build_rule_events(rule)

        assert len(result) == 1
        assert mock_ee.call_args_list[0].kwargs["starts_at"].date() == date(2026, 3, 2)

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}._get_calendar_id")
    def test_daily_anchor_beyond_range_end_produces_no_events(
        self, mock_get_cal, mock_tz, mock_localize, mock_to_utc
    ):
        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_cal.return_value = ("cal-1", [])
        rule = ProviderAvailabilityRule(
            id="rule-daily",
            provider_id=PROVIDER_ID,
            location_ids=[LOCATION_ID],
            recurrence_frequency="daily",
            effective_start=date(2026, 4, 1),  # future
            effective_end=date(2026, 3, 15),   # before anchor
            time_windows=[TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
        )
        with patch(f"{MODULE}.date") as mock_date:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            result = _build_rule_events(rule)
        assert result == []

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}._get_calendar_id")
    def test_daily_emits_oneoff_for_open_override_and_skips_closed(
        self, mock_get_cal, mock_tz, mock_localize, mock_to_utc
    ):
        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_cal.return_value = ("cal-1", [])
        rule = ProviderAvailabilityRule(
            id="rule-daily",
            provider_id=PROVIDER_ID,
            location_ids=[LOCATION_ID],
            recurrence_frequency="daily",
            time_windows=[TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
            date_overrides=[
                DateOverride(
                    date=date(2026, 3, 10),
                    is_closed=False,
                    time_windows=[TimeWindow(start=dt.time(14, 0), end=dt.time(15, 0))],
                ),
                DateOverride(date=date(2026, 3, 11), is_closed=True, time_windows=[]),
                DateOverride(date=date(2026, 3, 12), is_closed=False, time_windows=[]),
            ],
        )
        with patch(f"{MODULE}.date") as mock_date, \
             patch(f"{MODULE}.EventEffect") as mock_ee:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            result = _build_rule_events(rule)

        # 1 daily recurring event + 1 one-off for the open override (closed + empty skipped)
        assert len(result) == 2
        kwargs = [c.kwargs for c in mock_ee.call_args_list]
        oneoffs = [k for k in kwargs if "recurrence_frequency" not in k]
        assert len(oneoffs) == 1
        assert oneoffs[0]["starts_at"].date() == date(2026, 3, 10)


# ── build_recurring_block_sync_effects: daily + segment splitting ─────


class TestBuildRecurringBlockSyncDaily:
    @pytest.fixture(autouse=True)
    def _mock_override_map(self):
        with patch(f"{MODULE}.get_rules_for_provider", return_value=[]):
            yield

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    @patch(f"{MODULE}.build_delete_recurring_block_effects")
    def test_daily_recurring_block_creates_daily_events(
        self, mock_delete, mock_get_admin_cal, mock_tz, mock_localize, mock_to_utc,
    ):
        mock_delete.return_value = []
        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_admin_cal.return_value = ("admin-cal-1", [])
        block = RecurringBlock(
            id="rb-daily",
            provider_id=PROVIDER_ID,
            reason="Daily lunch",
            recurrence_frequency="daily",
            time_windows=[TimeWindow(start=dt.time(12, 0), end=dt.time(13, 0))],
            is_active=True,
        )
        with patch(f"{MODULE}.date") as mock_date, \
             patch(f"{MODULE}.EventEffect") as mock_ee:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            result = build_recurring_block_sync_effects(block)

        assert len(result) == 1
        init_kwargs = mock_ee.call_args_list[0].kwargs
        assert init_kwargs["recurrence_frequency"] == EventRecurrence.Daily
        assert init_kwargs["title"] == "Daily lunch"

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    @patch(f"{MODULE}.build_delete_recurring_block_effects")
    def test_daily_recurring_anchor_beyond_range_skips(
        self, mock_delete, mock_get_admin_cal, mock_tz, mock_localize, mock_to_utc,
    ):
        mock_delete.return_value = []
        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_admin_cal.return_value = ("admin-cal-1", [])
        block = RecurringBlock(
            id="rb-daily",
            provider_id=PROVIDER_ID,
            reason="Future block",
            recurrence_frequency="daily",
            effective_start=date(2026, 4, 1),
            effective_end=date(2026, 3, 15),
            time_windows=[TimeWindow(start=dt.time(12, 0), end=dt.time(13, 0))],
            is_active=True,
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
    def test_weekly_recurring_block_splits_around_override(
        self, mock_delete, mock_get_admin_cal, mock_tz, mock_localize, mock_to_utc,
    ):
        """An override on the block's weekday that narrows availability splits the recurring event."""
        mock_delete.return_value = []
        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_admin_cal.return_value = ("admin-cal-1", [])
        block = RecurringBlock(
            id="rb-weekly",
            provider_id=PROVIDER_ID,
            reason="Friday lunch",
            weekly_schedule={
                "friday": [TimeWindow(start=dt.time(12, 0), end=dt.time(13, 0))],
            },
            is_active=True,
        )
        override_rule = ProviderAvailabilityRule(
            id="rule-ovr",
            provider_id=PROVIDER_ID,
            weekly_schedule={},
            date_overrides=[
                DateOverride(
                    date=date(2026, 3, 20),  # a Friday
                    is_closed=False,
                    time_windows=[TimeWindow(start=dt.time(9, 0), end=dt.time(11, 0))],
                ),
            ],
        )
        with patch(f"{MODULE}.date") as mock_date, \
             patch(f"{MODULE}.get_rules_for_provider", return_value=[override_rule]), \
             patch(f"{MODULE}.EventEffect") as mock_ee:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            result = build_recurring_block_sync_effects(block)

        # The single recurring event is split into segments around the override Friday
        assert len(result) >= 2
        kwargs = [c.kwargs for c in mock_ee.call_args_list]
        assert all(k["recurrence_frequency"] == EventRecurrence.Weekly for k in kwargs)


# ── _build_hold_block_events ──────────────────────────────────────────


class TestBuildHoldBlockEvents:
    @pytest.fixture(autouse=True)
    def _mock_override_map(self):
        with patch(f"{MODULE}.get_rules_for_provider", return_value=[]):
            yield

    def test_hold_type_none_returns_empty(self, sample_recurring_block):
        sample_recurring_block.hold_type = "none"
        assert _build_hold_block_events(sample_recurring_block) == []

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    def test_same_day_hold_blocks_future_in_pattern_dates(
        self, mock_get_admin_cal, mock_tz, mock_localize, mock_to_utc,
    ):
        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_admin_cal.return_value = ("admin-cal-1", [])
        block = RecurringBlock(
            id="rb-hold",
            provider_id=PROVIDER_ID,
            reason="Hold",
            weekly_schedule={
                "friday": [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
            },
            hold_type="same_day",
            is_active=True,
        )
        with patch(f"{MODULE}.date") as mock_date, \
             patch(f"{MODULE}.EventEffect") as mock_ee:
            mock_date.today.return_value = date(2026, 3, 2)  # Monday
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            result = _build_hold_block_events(block)

        # Fridays within the 30-day rolling window: 3/6, 3/13, 3/20, 3/27 = 4 events
        assert len(result) == 4
        kwargs = [c.kwargs for c in mock_ee.call_args_list]
        assert all(k["title"] == "Same Day Hold: Hold" for k in kwargs)
        assert all("recurrence_frequency" not in k for k in kwargs)

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    def test_next_day_hold_uses_next_day_label(
        self, mock_get_admin_cal, mock_tz, mock_localize, mock_to_utc,
    ):
        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_admin_cal.return_value = ("admin-cal-1", [])
        block = RecurringBlock(
            id="rb-hold",
            provider_id=PROVIDER_ID,
            reason="",
            recurrence_frequency="daily",
            time_windows=[TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
            hold_type="next_day",
            is_active=True,
        )
        with patch(f"{MODULE}.date") as mock_date, \
             patch(f"{MODULE}.EventEffect") as mock_ee:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            result = _build_hold_block_events(block)

        # daily hold: every day from today+2 .. today+30 = 29 events
        assert len(result) == 29
        kwargs = [c.kwargs for c in mock_ee.call_args_list]
        assert all(k["title"] == "Next Day Hold" for k in kwargs)

    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz")
    @patch(f"{MODULE}.get_admin_calendar_id")
    def test_hold_no_admin_calendar_skips_location(
        self, mock_get_admin_cal, mock_tz, mock_localize, mock_to_utc,
    ):
        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_admin_cal.return_value = ("", [])
        block = RecurringBlock(
            id="rb-hold",
            provider_id=PROVIDER_ID,
            recurrence_frequency="daily",
            time_windows=[TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
            hold_type="same_day",
            is_active=True,
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
    def test_hold_suppressed_on_override_outside_window(
        self, mock_get_admin_cal, mock_tz, mock_localize, mock_to_utc,
    ):
        mock_tz.return_value = ZoneInfo("US/Eastern")
        mock_get_admin_cal.return_value = ("admin-cal-1", [])
        block = RecurringBlock(
            id="rb-hold",
            provider_id=PROVIDER_ID,
            reason="Hold",
            recurrence_frequency="daily",
            time_windows=[TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
            hold_type="same_day",
            is_active=True,
        )
        override_rule = ProviderAvailabilityRule(
            id="rule-ovr",
            provider_id=PROVIDER_ID,
            weekly_schedule={},
            date_overrides=[
                DateOverride(
                    date=date(2026, 3, 6),
                    is_closed=False,
                    time_windows=[TimeWindow(start=dt.time(14, 0), end=dt.time(15, 0))],
                ),
            ],
        )
        with patch(f"{MODULE}.date") as mock_date, \
             patch(f"{MODULE}.get_rules_for_provider", return_value=[override_rule]), \
             patch(f"{MODULE}.EventEffect") as mock_ee:
            mock_date.today.return_value = date(2026, 3, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            result = _build_hold_block_events(block)

        # same_day hold blocks 3/3..4/1 = 30 days, minus the suppressed 3/6 = 29
        assert len(result) == 29
        starts = {c.kwargs["starts_at"].date() for c in mock_ee.call_args_list}
        assert date(2026, 3, 6) not in starts


# ── build_hold_block_refresh_effects ──────────────────────────────────


class TestBuildHoldBlockRefreshEffects:
    @patch(f"{MODULE}._build_hold_block_events")
    @patch(f"{MODULE}.get_admin_calendars")
    def test_deletes_existing_then_recreates(
        self, mock_get_cals, mock_build_hold, sample_recurring_block
    ):
        cal = MagicMock()
        cal.id = "admin-cal-1"
        mock_get_cals.return_value = [cal]

        evt = MagicMock()
        evt.id = "evt-1"
        with patch(f"{MODULE}.EventModel") as mock_event_model:
            mock_event_model.objects.filter.side_effect = (
                [[evt]] + [[] for _ in range(10)]
            )
            recreate = MagicMock()
            mock_build_hold.return_value = [recreate]

            result = build_hold_block_refresh_effects(sample_recurring_block)

        # 1 delete effect + 1 recreate effect
        assert len(result) == 2
        assert result[-1] is recreate
        assert mock_build_hold.mock_calls == [call(sample_recurring_block)]

    @patch(f"{MODULE}._build_hold_block_events", return_value=[])
    @patch(f"{MODULE}.get_admin_calendars", return_value=[])
    def test_no_calendars_only_recreates(
        self, mock_get_cals, mock_build_hold, sample_recurring_block
    ):
        result = build_hold_block_refresh_effects(sample_recurring_block)
        assert result == []
        assert mock_build_hold.mock_calls == [call(sample_recurring_block)]


# ── build_delete_recurring_block_effects: hold cleanup branches ───────


class TestBuildDeleteRecurringBlockHoldCleanup:
    @patch(f"{MODULE}.EventModel")
    @patch(f"{MODULE}.get_admin_calendars")
    @patch(f"{MODULE}.get_event_ids")
    def test_stored_ids_path_also_cleans_hold_events(
        self, mock_get_ids, mock_get_cals, mock_event_model, sample_recurring_block
    ):
        sample_recurring_block.hold_type = "same_day"
        mock_get_ids.return_value = ["stored-1", "stored-2"]
        cal = MagicMock()
        cal.id = "admin-cal-1"
        mock_get_cals.return_value = [cal]
        hold_evt = MagicMock()
        hold_evt.id = "hold-1"
        mock_event_model.objects.filter.side_effect = (
            [[hold_evt]] + [[] for _ in range(10)]
        )

        result = build_delete_recurring_block_effects(
            sample_recurring_block.provider_id, sample_recurring_block
        )
        # 2 stored-id deletes + 1 hold-event delete
        assert len(result) == 3

    @patch(f"{MODULE}.EventModel")
    @patch(f"{MODULE}.get_admin_calendars")
    @patch(f"{MODULE}.get_event_ids")
    def test_title_fallback_path_also_cleans_hold_events(
        self, mock_get_ids, mock_get_cals, mock_event_model, sample_recurring_block
    ):
        sample_recurring_block.hold_type = "next_day"
        mock_get_ids.return_value = []  # force title-fallback path
        cal = MagicMock()
        cal.id = "admin-cal-1"
        mock_get_cals.return_value = [cal]
        title_evt = MagicMock()
        title_evt.id = "title-1"
        hold_evt = MagicMock()
        hold_evt.id = "hold-1"
        mock_event_model.objects.filter.side_effect = (
            [[title_evt], [hold_evt]] + [[] for _ in range(10)]
        )

        result = build_delete_recurring_block_effects(
            sample_recurring_block.provider_id, sample_recurring_block
        )
        # 1 title-match delete + 1 hold-event delete
        assert len(result) == 2
