"""Tests for provider_availability.cron.cache_refresh."""

import datetime as dt
from datetime import date, timedelta
import pytest
from unittest.mock import MagicMock, call, patch

from provider_availability.cron.cache_refresh import (
    _reconcile_if_schedulable_changed,
    CacheRefreshTask,
    _daily_resync,
    _ensure_provider_calendars,
    _prune_expired,
    _refresh_hold_blocks,
    _refresh_lead_time_blocks,
)
from provider_availability.engine.models import (
    AdminBlock,
    BookingInterval,
    DateOverride,
    RecurringBlock,
    ProviderAvailabilityRule,
    TimeWindow,
)


CR_MODULE = "provider_availability.cron.cache_refresh"


class TestCacheRefreshTaskExecute:
    """Test that execute() orchestrates TTL refresh and delegates to helpers."""

    @pytest.fixture(autouse=True)
    def _no_schedulable_change(self):
        with patch(f"{CR_MODULE}.get_schedulable_staff", return_value=[]), \
             patch(f"{CR_MODULE}._reconcile_if_schedulable_changed", return_value=[]), \
             patch(f"{CR_MODULE}._prune_expired", return_value=0) as prune:
            self.prune = prune
            yield

    def test_execute_calls_refresh_when_due(self):
        handler = CacheRefreshTask(MagicMock())

        with patch(f"{CR_MODULE}.should_refresh_ttls", return_value=True) as mock_should, \
             patch(f"{CR_MODULE}.refresh_all_ttls", return_value=5) as mock_refresh, \
             patch(f"{CR_MODULE}.get_last_sync_date", return_value=date.today().isoformat()), \
             patch(f"{CR_MODULE}._ensure_provider_calendars", return_value=[]) as mock_cal, \
             patch(f"{CR_MODULE}._daily_resync", return_value=[]) as mock_resync, \
             patch(f"{CR_MODULE}._refresh_lead_time_blocks", return_value=[]) as mock_lead, \
             patch(f"{CR_MODULE}._refresh_hold_blocks", return_value=[]) as mock_hold:

            result = handler.execute()

            assert mock_should.mock_calls == [call()]
            assert mock_refresh.mock_calls == [call()]
            assert mock_cal.mock_calls == [call([])]
            assert mock_resync.mock_calls == [call()]
            assert mock_lead.mock_calls == [call()]
            # Same day → hold refresh is NOT run
            assert mock_hold.mock_calls == []
            assert result == []

    def test_execute_skips_refresh_when_not_due(self):
        handler = CacheRefreshTask(MagicMock())

        with patch(f"{CR_MODULE}.should_refresh_ttls", return_value=False) as mock_should, \
             patch(f"{CR_MODULE}.refresh_all_ttls") as mock_refresh, \
             patch(f"{CR_MODULE}.get_last_sync_date", return_value=date.today().isoformat()), \
             patch(f"{CR_MODULE}._ensure_provider_calendars", return_value=[]) as mock_cal, \
             patch(f"{CR_MODULE}._daily_resync", return_value=[]) as mock_resync, \
             patch(f"{CR_MODULE}._refresh_lead_time_blocks", return_value=[]) as mock_lead, \
             patch(f"{CR_MODULE}._refresh_hold_blocks", return_value=[]):

            result = handler.execute()

            assert mock_should.mock_calls == [call()]
            assert mock_refresh.mock_calls == []
            assert result == []

    def test_execute_refreshes_holds_only_on_day_change(self):
        """Hold refresh runs when the day rolled over, and is skipped otherwise."""
        handler = CacheRefreshTask(MagicMock())
        hold_effect = MagicMock()

        common = {
            "should_refresh_ttls": patch(f"{CR_MODULE}.should_refresh_ttls", return_value=False),
            "cal": patch(f"{CR_MODULE}._ensure_provider_calendars", return_value=[]),
            "resync": patch(f"{CR_MODULE}._daily_resync", return_value=[]),
            "lead": patch(f"{CR_MODULE}._refresh_lead_time_blocks", return_value=[]),
        }

        # Day changed (last sync was yesterday) → hold refresh runs
        with common["should_refresh_ttls"], common["cal"], common["resync"], common["lead"], \
             patch(f"{CR_MODULE}.get_last_sync_date", return_value="2000-01-01"), \
             patch(f"{CR_MODULE}._refresh_hold_blocks", return_value=[hold_effect]) as mock_hold:
            result = handler.execute()
            assert mock_hold.mock_calls == [call()]
            assert result == [hold_effect]
            assert self.prune.mock_calls == [call()]

        # Same day → hold refresh skipped
        with patch(f"{CR_MODULE}.should_refresh_ttls", return_value=False), \
             patch(f"{CR_MODULE}._ensure_provider_calendars", return_value=[]), \
             patch(f"{CR_MODULE}._daily_resync", return_value=[]), \
             patch(f"{CR_MODULE}._refresh_lead_time_blocks", return_value=[]), \
             patch(f"{CR_MODULE}.get_last_sync_date", return_value=date.today().isoformat()), \
             patch(f"{CR_MODULE}._refresh_hold_blocks", return_value=[hold_effect]) as mock_hold2:
            result = handler.execute()
            assert mock_hold2.mock_calls == []
            assert result == []
            # Pruning is once a day too: still only the call from the day change
            assert self.prune.mock_calls == [call()]

    def test_execute_aggregates_effects(self):
        handler = CacheRefreshTask(MagicMock())

        cal_effect = MagicMock()
        resync_effect = MagicMock()
        lead_effect = MagicMock()

        with patch(f"{CR_MODULE}.should_refresh_ttls", return_value=False), \
             patch(f"{CR_MODULE}.get_last_sync_date", return_value=date.today().isoformat()), \
             patch(f"{CR_MODULE}._ensure_provider_calendars", return_value=[cal_effect]), \
             patch(f"{CR_MODULE}._daily_resync", return_value=[resync_effect]), \
             patch(f"{CR_MODULE}._refresh_lead_time_blocks", return_value=[lead_effect]), \
             patch(f"{CR_MODULE}._refresh_hold_blocks", return_value=[]):

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
             patch(f"{CR_MODULE}.get_schedulable_provider_ids", return_value={"p1", "p2"}), \
             patch(f"{CR_MODULE}.sync_provider_availability", return_value=["effect1"]) as mock_sync, \
             patch(f"{CR_MODULE}.set_last_sync_date") as mock_set:

            result = _daily_resync()

            assert mock_rules.mock_calls == [call()]
            assert mock_sync.mock_calls == [call("p1", schedulable_ids={"p1", "p2"})]
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
             patch(f"{CR_MODULE}.get_schedulable_provider_ids", return_value={"p1", "p2"}), \
             patch(f"{CR_MODULE}.sync_provider_availability", return_value=[]) as mock_sync, \
             patch(f"{CR_MODULE}.set_last_sync_date") as mock_set:

            result = _daily_resync()

            assert mock_sync.mock_calls == [call("p2", schedulable_ids={"p1", "p2"})]
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
             patch(f"{CR_MODULE}.get_schedulable_provider_ids", return_value={"p1"}), \
             patch(f"{CR_MODULE}.sync_provider_availability", return_value=[]) as mock_sync, \
             patch(f"{CR_MODULE}.set_last_sync_date"):

            result = _daily_resync()

            # Only one call despite two matching rules for same provider
            assert mock_sync.mock_calls == [call("p1", schedulable_ids={"p1"})]

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

    def _mock_existing(self, mock_cal, existing_keys):
        """Configure CalendarModel.objects.filter(...).values_list(...) to return keys."""
        mock_cal.filter.return_value.values_list.return_value = existing_keys

    def test_creates_calendar_for_provider_missing_one(self):
        staff = MagicMock()
        staff.id = "staff-uuid-1"
        staff.first_name = "Alice"
        staff.last_name = "Smith"

        with patch(f"{CR_MODULE}.get_schedulable_staff", return_value=[staff]) as mock_sched, \
             patch(f"{CR_MODULE}.CalendarModel.objects") as mock_cal, \
             patch(f"{CR_MODULE}.uuid4", return_value="new-cal-uuid"):
            self._mock_existing(mock_cal, [])  # no existing calendars

            result = _ensure_provider_calendars()

            assert mock_sched.mock_calls == [call()]
            # single bulk lookup, not one query per provider
            assert mock_cal.mock_calls == [
                call.filter(description__in=["staff-uuid-1"]),
                call.filter().values_list("description", flat=True),
            ]
            assert len(result) == 1

    def test_skips_provider_with_existing_calendar(self):
        staff = MagicMock()
        staff.id = "staff-uuid-2"

        with patch(f"{CR_MODULE}.get_schedulable_staff", return_value=[staff]), \
             patch(f"{CR_MODULE}.CalendarModel.objects") as mock_cal:
            self._mock_existing(mock_cal, ["staff-uuid-2"])  # already has one

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

        with patch(f"{CR_MODULE}.get_schedulable_staff", return_value=[staff_a, staff_b]), \
             patch(f"{CR_MODULE}.CalendarModel.objects") as mock_cal, \
             patch(f"{CR_MODULE}.uuid4", return_value="cal-uuid"):
            # staff_a has no calendar, staff_b has one
            self._mock_existing(mock_cal, ["staff-b"])

            result = _ensure_provider_calendars()

            # Only staff_a should get a calendar
            assert len(result) == 1

    def test_no_active_providers(self):
        with patch(f"{CR_MODULE}.get_schedulable_staff", return_value=[]), \
             patch(f"{CR_MODULE}.CalendarModel.objects") as mock_cal:
            self._mock_existing(mock_cal, [])
            result = _ensure_provider_calendars()

            assert result == []

    def test_exception_is_caught(self):
        with patch(f"{CR_MODULE}.get_schedulable_staff", side_effect=RuntimeError("db error")):
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


class TestScheduleLookupFailure:
    def test_a_failed_lookup_still_runs_the_other_refreshes(self):
        handler = CacheRefreshTask(MagicMock())
        lead_effect = MagicMock()

        with patch(f"{CR_MODULE}.should_refresh_ttls", return_value=False), \
             patch(f"{CR_MODULE}.get_last_sync_date", return_value=date.today().isoformat()), \
             patch(f"{CR_MODULE}.get_schedulable_staff", side_effect=RuntimeError("db down")), \
             patch(f"{CR_MODULE}._ensure_provider_calendars") as mock_cal, \
             patch(f"{CR_MODULE}._reconcile_if_schedulable_changed") as mock_rec, \
             patch(f"{CR_MODULE}._daily_resync", return_value=[]) as mock_resync, \
             patch(f"{CR_MODULE}._refresh_lead_time_blocks", return_value=[lead_effect]):

            result = handler.execute()

            assert result == [lead_effect]
            assert mock_resync.mock_calls == [call()]
            assert mock_cal.mock_calls == []
            assert mock_rec.mock_calls == []


class TestReconcileWhenSchedulableChanges:
    """Who is bookable can change outside the plugin (a role edit, an
    activation, the Provider role type fallback switching). Availability is
    rebuilt when it does, and left alone when it does not."""

    def test_first_tick_only_records_the_set(self):
        with patch(f"{CR_MODULE}.get_seen_schedulable_ids", return_value=None), \
             patch(f"{CR_MODULE}.set_seen_schedulable_ids") as mock_set, \
             patch("provider_availability.api.availability_api._reconcile_availability_to_roles") as mock_rec:
            assert _reconcile_if_schedulable_changed({"b", "a"}) == []
            assert mock_set.mock_calls == [call(["a", "b"])]
            assert mock_rec.mock_calls == []

    def test_unchanged_set_does_nothing(self):
        with patch(f"{CR_MODULE}.get_seen_schedulable_ids", return_value=["a", "b"]), \
             patch("provider_availability.api.availability_api._reconcile_availability_to_roles") as mock_rec:
            assert _reconcile_if_schedulable_changed({"a", "b"}) == []
            assert mock_rec.mock_calls == []

    def test_changed_set_rebuilds_availability(self):
        with patch(f"{CR_MODULE}.get_seen_schedulable_ids", return_value=["a"]), \
             patch("provider_availability.api.availability_api._reconcile_availability_to_roles",
                   return_value=["sync"]) as mock_rec:
            assert _reconcile_if_schedulable_changed({"a", "b"}) == ["sync"]
            assert mock_rec.mock_calls == [call()]


class TestPruneExpired:
    """Items that ended over 30 days ago leave the lists; nothing touches calendars."""

    TODAY = date(2026, 10, 5)  # cutoff is 2026-09-05

    def _rule(self, end, overrides=()):
        return ProviderAvailabilityRule(
            provider_id="p1", id="r-" + str(end), effective_end=end,
            date_overrides=[DateOverride(date=d) for d in overrides],
        )

    def test_drops_only_items_past_the_cutoff(self):
        old_rule = self._rule(date(2026, 9, 1))
        recent_rule = self._rule(date(2026, 9, 20), overrides=[date(2026, 8, 1), date(2026, 9, 10)])
        open_rule = self._rule(None)
        old_block = AdminBlock(provider_id="p1", id="b-old", start=dt.datetime(2026, 9, 1, 9), end=dt.datetime(2026, 9, 1, 10))
        edge_block = AdminBlock(provider_id="p1", id="b-edge", start=dt.datetime(2026, 9, 5, 9), end=dt.datetime(2026, 9, 5, 10))
        old_rb = RecurringBlock(provider_id="p1", id="rb-old", effective_end=date(2026, 8, 31))
        live_rb = RecurringBlock(provider_id="p1", id="rb-live", effective_end=None)

        with patch(f"{CR_MODULE}.get_all_rules", return_value=[old_rule, recent_rule, open_rule]), \
             patch(f"{CR_MODULE}.get_all_blocks", return_value=[old_block, edge_block]), \
             patch(f"{CR_MODULE}.get_all_recurring_blocks", return_value=[old_rb, live_rb]), \
             patch(f"{CR_MODULE}.delete_rule_by_id") as del_rule, \
             patch(f"{CR_MODULE}.delete_block") as del_block, \
             patch(f"{CR_MODULE}.delete_recurring_block") as del_rb, \
             patch(f"{CR_MODULE}.delete_event_ids") as del_ids, \
             patch(f"{CR_MODULE}.save_rule") as save:
            removed = _prune_expired(self.TODAY)

        # old rule, one old override, old block, old recurring block
        assert removed == 4
        assert del_rule.mock_calls == [call("p1", old_rule.id)]
        assert del_block.mock_calls == [call("p1", "b-old")]
        assert del_rb.mock_calls == [call("p1", "rb-old")]
        assert del_ids.mock_calls == [call(old_rule.id), call("b-old"), call("rb-old")]
        # The recent rule keeps its in-window override and loses the old one
        assert save.mock_calls == [call(recent_rule)]
        assert [o.date for o in recent_rule.date_overrides] == [date(2026, 9, 10)]

    def test_nothing_expired_saves_nothing(self):
        with patch(f"{CR_MODULE}.get_all_rules", return_value=[self._rule(None)]), \
             patch(f"{CR_MODULE}.get_all_blocks", return_value=[]), \
             patch(f"{CR_MODULE}.get_all_recurring_blocks", return_value=[]), \
             patch(f"{CR_MODULE}.save_rule") as save:
            assert _prune_expired(self.TODAY) == 0
        assert save.mock_calls == []

    def test_error_is_logged_not_raised(self):
        with patch(f"{CR_MODULE}.get_all_rules", side_effect=RuntimeError("cache down")):
            assert _prune_expired(self.TODAY) == 0
