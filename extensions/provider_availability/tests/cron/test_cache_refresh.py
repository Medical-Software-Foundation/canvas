"""Tests for provider_availability.cron.cache_refresh."""

import datetime as dt
from datetime import date, timedelta
from unittest.mock import MagicMock, call, patch

from provider_availability.cron.cache_refresh import (
    CacheRefreshTask,
    _daily_resync,
    _ensure_provider_calendars,
    _refresh_hold_blocks,
    _refresh_lead_time_blocks,
)
from provider_availability.engine.models import (
    BookingInterval,
    ProviderAvailabilityRule,
    TimeWindow,
)


CR_MODULE = "provider_availability.cron.cache_refresh"


class TestCacheRefreshTaskExecute:
    """Test that execute() orchestrates TTL refresh and delegates to helpers."""

    def test_execute_calls_refresh_when_due(self):
        handler = CacheRefreshTask(MagicMock())

        with patch(f"{CR_MODULE}.should_refresh_ttls", return_value=True) as mock_should, \
             patch(f"{CR_MODULE}.refresh_all_ttls", return_value=5) as mock_refresh, \
             patch(f"{CR_MODULE}._ensure_provider_calendars", return_value=[]) as mock_cal, \
             patch(f"{CR_MODULE}._daily_resync", return_value=[]) as mock_resync, \
             patch(f"{CR_MODULE}._refresh_lead_time_blocks", return_value=[]) as mock_lead:

            result = handler.execute()

            assert mock_should.mock_calls == [call()]
            assert mock_refresh.mock_calls == [call()]
            assert mock_cal.mock_calls == [call()]
            assert mock_resync.mock_calls == [call()]
            assert mock_lead.mock_calls == [call()]
            assert result == []

    def test_execute_skips_refresh_when_not_due(self):
        handler = CacheRefreshTask(MagicMock())

        with patch(f"{CR_MODULE}.should_refresh_ttls", return_value=False) as mock_should, \
             patch(f"{CR_MODULE}.refresh_all_ttls") as mock_refresh, \
             patch(f"{CR_MODULE}._ensure_provider_calendars", return_value=[]) as mock_cal, \
             patch(f"{CR_MODULE}._daily_resync", return_value=[]) as mock_resync, \
             patch(f"{CR_MODULE}._refresh_lead_time_blocks", return_value=[]) as mock_lead:

            result = handler.execute()

            assert mock_should.mock_calls == [call()]
            assert mock_refresh.mock_calls == []
            assert result == []

    def test_execute_aggregates_effects(self):
        handler = CacheRefreshTask(MagicMock())

        cal_effect = MagicMock()
        resync_effect = MagicMock()
        lead_effect = MagicMock()

        with patch(f"{CR_MODULE}.should_refresh_ttls", return_value=False), \
             patch(f"{CR_MODULE}._ensure_provider_calendars", return_value=[cal_effect]), \
             patch(f"{CR_MODULE}._daily_resync", return_value=[resync_effect]), \
             patch(f"{CR_MODULE}._refresh_lead_time_blocks", return_value=[lead_effect]):

            result = handler.execute()

            assert result == [cal_effect, resync_effect, lead_effect]


class TestDailyResync:
    """Test _daily_resync: only syncs on date change and for boundary rules."""

    def test_skips_when_already_synced_today(self):
        today_str = date.today().isoformat()

        with patch(f"{CR_MODULE}.get_last_sync_date", return_value=today_str) as mock_get, \
             patch(f"{CR_MODULE}.get_all_rules") as mock_rules:

            result = _daily_resync()

            assert mock_get.mock_calls == [call()]
            assert mock_rules.mock_calls == []
            assert result == []

    def test_syncs_on_new_day(self):
        yesterday_str = (date.today() - timedelta(days=1)).isoformat()
        today = date.today()

        rule_starting_today = MagicMock()
        rule_starting_today.is_active = True
        rule_starting_today.weekly_schedule = {"monday": []}
        rule_starting_today.effective_start = today
        rule_starting_today.effective_end = None
        rule_starting_today.provider_id = "p1"

        with patch(f"{CR_MODULE}.get_last_sync_date", return_value=yesterday_str), \
             patch(f"{CR_MODULE}.get_all_rules", return_value=[rule_starting_today]) as mock_rules, \
             patch(f"{CR_MODULE}.sync_provider_availability", return_value=["effect1"]) as mock_sync, \
             patch(f"{CR_MODULE}.set_last_sync_date") as mock_set:

            result = _daily_resync()

            assert mock_rules.mock_calls == [call()]
            assert mock_sync.mock_calls == [call("p1")]
            assert mock_set.mock_calls == [call(today.isoformat())]
            assert result == ["effect1"]

    def test_syncs_rule_expiring_yesterday(self):
        today = date.today()
        yesterday = today - timedelta(days=1)

        rule_expired_yesterday = MagicMock()
        rule_expired_yesterday.is_active = True
        rule_expired_yesterday.weekly_schedule = {"tuesday": []}
        rule_expired_yesterday.effective_start = None
        rule_expired_yesterday.effective_end = yesterday
        rule_expired_yesterday.provider_id = "p2"

        with patch(f"{CR_MODULE}.get_last_sync_date", return_value=""), \
             patch(f"{CR_MODULE}.get_all_rules", return_value=[rule_expired_yesterday]), \
             patch(f"{CR_MODULE}.sync_provider_availability", return_value=[]) as mock_sync, \
             patch(f"{CR_MODULE}.set_last_sync_date") as mock_set:

            result = _daily_resync()

            assert mock_sync.mock_calls == [call("p2")]
            assert mock_set.mock_calls == [call(today.isoformat())]

    def test_skips_inactive_rule(self):
        today = date.today()

        inactive_rule = MagicMock()
        inactive_rule.is_active = False
        inactive_rule.weekly_schedule = {"monday": []}
        inactive_rule.effective_start = today
        inactive_rule.provider_id = "p3"

        with patch(f"{CR_MODULE}.get_last_sync_date", return_value=""), \
             patch(f"{CR_MODULE}.get_all_rules", return_value=[inactive_rule]), \
             patch(f"{CR_MODULE}.sync_provider_availability") as mock_sync, \
             patch(f"{CR_MODULE}.set_last_sync_date"):

            result = _daily_resync()

            assert mock_sync.mock_calls == []
            assert result == []

    def test_skips_rule_without_weekly_schedule(self):
        today = date.today()

        rule_no_schedule = MagicMock()
        rule_no_schedule.is_active = True
        rule_no_schedule.weekly_schedule = {}
        rule_no_schedule.effective_start = today
        rule_no_schedule.provider_id = "p4"

        with patch(f"{CR_MODULE}.get_last_sync_date", return_value=""), \
             patch(f"{CR_MODULE}.get_all_rules", return_value=[rule_no_schedule]), \
             patch(f"{CR_MODULE}.sync_provider_availability") as mock_sync, \
             patch(f"{CR_MODULE}.set_last_sync_date"):

            result = _daily_resync()

            assert mock_sync.mock_calls == []
            assert result == []

    def test_deduplicates_providers(self):
        """When multiple rules match for the same provider, only sync once."""
        today = date.today()
        yesterday = today - timedelta(days=1)

        rule_a = MagicMock()
        rule_a.is_active = True
        rule_a.weekly_schedule = {"monday": []}
        rule_a.effective_start = today
        rule_a.effective_end = None
        rule_a.provider_id = "p1"

        rule_b = MagicMock()
        rule_b.is_active = True
        rule_b.weekly_schedule = {"tuesday": []}
        rule_b.effective_start = None
        rule_b.effective_end = yesterday
        rule_b.provider_id = "p1"

        with patch(f"{CR_MODULE}.get_last_sync_date", return_value=""), \
             patch(f"{CR_MODULE}.get_all_rules", return_value=[rule_a, rule_b]), \
             patch(f"{CR_MODULE}.sync_provider_availability", return_value=[]) as mock_sync, \
             patch(f"{CR_MODULE}.set_last_sync_date"):

            result = _daily_resync()

            # Only one call despite two matching rules for same provider
            assert mock_sync.mock_calls == [call("p1")]

    def test_exception_is_caught(self):
        """An exception in get_all_rules should be caught and return empty."""
        with patch(f"{CR_MODULE}.get_last_sync_date", return_value=""), \
             patch(f"{CR_MODULE}.get_all_rules", side_effect=RuntimeError("boom")):

            result = _daily_resync()

            assert result == []


class TestRefreshLeadTimeBlocks:
    """Test _refresh_lead_time_blocks."""

    def test_calls_build_for_active_rules_with_lead_time(self):
        rule_with_lead = MagicMock()
        rule_with_lead.is_active = True
        rule_with_lead.booking_interval.min_lead_hours = 24

        rule_no_lead = MagicMock()
        rule_no_lead.is_active = True
        rule_no_lead.booking_interval.min_lead_hours = 0

        rule_inactive = MagicMock()
        rule_inactive.is_active = False
        rule_inactive.booking_interval.min_lead_hours = 48

        lead_effect = MagicMock()

        with patch(f"{CR_MODULE}.get_all_rules", return_value=[rule_with_lead, rule_no_lead, rule_inactive]) as mock_rules, \
             patch(f"{CR_MODULE}.build_lead_time_block_effects", return_value=[lead_effect]) as mock_build:

            result = _refresh_lead_time_blocks()

            assert mock_rules.mock_calls == [call()]
            assert mock_build.mock_calls == [call(rule_with_lead)]
            assert result == [lead_effect]

    def test_no_rules(self):
        with patch(f"{CR_MODULE}.get_all_rules", return_value=[]), \
             patch(f"{CR_MODULE}.build_lead_time_block_effects") as mock_build:

            result = _refresh_lead_time_blocks()

            assert mock_build.mock_calls == []
            assert result == []

    def test_exception_is_caught(self):
        with patch(f"{CR_MODULE}.get_all_rules", side_effect=RuntimeError("boom")):

            result = _refresh_lead_time_blocks()

            assert result == []


class TestEnsureProviderCalendars:
    """Test _ensure_provider_calendars."""

    def test_creates_calendar_for_provider_missing_one(self):
        staff = MagicMock()
        staff.id = "staff-uuid-1"
        staff.first_name = "Alice"
        staff.last_name = "Smith"

        with patch(f"{CR_MODULE}.Staff.objects") as mock_staff, \
             patch(f"{CR_MODULE}.CalendarModel.objects") as mock_cal, \
             patch(f"{CR_MODULE}.uuid4", return_value="new-cal-uuid"):
            mock_staff.filter.return_value.distinct.return_value = [staff]
            mock_cal.filter.return_value.first.return_value = None

            result = _ensure_provider_calendars()

            assert mock_staff.mock_calls == [
                call.filter(active=True, roles__role_type="PROVIDER"),
                call.filter().distinct(),
            ]
            assert mock_cal.mock_calls == [
                call.filter(description="staff-uuid-1"),
                call.filter().first(),
            ]
            assert len(result) == 1

    def test_skips_provider_with_existing_calendar(self):
        staff = MagicMock()
        staff.id = "staff-uuid-2"

        with patch(f"{CR_MODULE}.Staff.objects") as mock_staff, \
             patch(f"{CR_MODULE}.CalendarModel.objects") as mock_cal:
            mock_staff.filter.return_value.distinct.return_value = [staff]
            mock_cal.filter.return_value.first.return_value = MagicMock()

            result = _ensure_provider_calendars()

            assert result == []

    def test_handles_multiple_providers(self):
        staff_a = MagicMock()
        staff_a.id = "staff-a"
        staff_a.first_name = "Alice"
        staff_a.last_name = "A"

        staff_b = MagicMock()
        staff_b.id = "staff-b"
        staff_b.first_name = "Bob"
        staff_b.last_name = "B"

        with patch(f"{CR_MODULE}.Staff.objects") as mock_staff, \
             patch(f"{CR_MODULE}.CalendarModel.objects") as mock_cal, \
             patch(f"{CR_MODULE}.uuid4", return_value="cal-uuid"):
            mock_staff.filter.return_value.distinct.return_value = [staff_a, staff_b]
            # staff_a has no calendar, staff_b has one
            mock_cal.filter.return_value.first.side_effect = [None, MagicMock()]

            result = _ensure_provider_calendars()

            # Only staff_a should get a calendar
            assert len(result) == 1

    def test_no_active_providers(self):
        with patch(f"{CR_MODULE}.Staff.objects") as mock_staff, \
             patch(f"{CR_MODULE}.CalendarModel.objects"):
            mock_staff.filter.return_value.distinct.return_value = []

            result = _ensure_provider_calendars()

            assert result == []

    def test_exception_is_caught(self):
        with patch(f"{CR_MODULE}.Staff.objects") as mock_staff:
            mock_staff.filter.side_effect = RuntimeError("db error")

            result = _ensure_provider_calendars()

            assert result == []


class TestRefreshHoldBlocks:
    def test_refreshes_active_hold_blocks(self):
        block = MagicMock()
        block.is_active = True
        block.hold_type = "same_day"

        with patch(f"{CR_MODULE}.get_all_recurring_blocks", return_value=[block]), \
             patch(f"{CR_MODULE}.build_hold_block_refresh_effects", return_value=[MagicMock()]) as mock_build:
            result = _refresh_hold_blocks()

            mock_build.assert_called_once_with(block)
            assert len(result) == 1

    def test_skips_inactive_blocks(self):
        block = MagicMock()
        block.is_active = False
        block.hold_type = "same_day"

        with patch(f"{CR_MODULE}.get_all_recurring_blocks", return_value=[block]), \
             patch(f"{CR_MODULE}.build_hold_block_refresh_effects") as mock_build:
            result = _refresh_hold_blocks()

            mock_build.assert_not_called()
            assert result == []

    def test_skips_blocks_with_no_hold(self):
        block = MagicMock()
        block.is_active = True
        block.hold_type = "none"

        with patch(f"{CR_MODULE}.get_all_recurring_blocks", return_value=[block]), \
             patch(f"{CR_MODULE}.build_hold_block_refresh_effects") as mock_build:
            result = _refresh_hold_blocks()

            mock_build.assert_not_called()
            assert result == []
