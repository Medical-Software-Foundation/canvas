"""Scheduling feature switches: what each one stops, cleans up and lists (engine.features)."""

import datetime as dt
from unittest.mock import MagicMock, call, patch

import pytest

from provider_availability.engine import features, settings
from provider_availability.engine.models import (
    AdminBlock,
    DateOverride,
    ProviderAvailabilityRule,
    RecurringBlock,
    TimeWindow,
)

MOD = "provider_availability.engine.features"
NOW = dt.datetime(2026, 10, 14, 15, 0, tzinfo=dt.UTC)
P1 = "c" * 32


def _evt(eid, start, end, title="Buffer"):
    e = MagicMock()
    e.id, e.starts_at, e.ends_at, e.title = eid, start, end, title
    return e


class _QS(list):
    def order_by(self, *a):
        return self

    def values_list(self, *a, flat=False):
        return self


class TestGates:
    def test_buffers_off_draws_no_buffers(self):
        from provider_availability.protocols.appointment_buffer import _create_buffer_effects

        settings.set_feature("buffers", False)
        appt = MagicMock()
        assert _create_buffer_effects(appt) == []
        assert appt.mock_calls == []

    def test_lead_time_off_draws_and_deletes_nothing(self):
        from provider_availability.engine.event_sync import build_provider_lead_time_effects

        settings.set_feature("lead_time", False)
        with patch("provider_availability.engine.event_sync.delete_provider_lead_time_events") as mock_delete:
            assert build_provider_lead_time_effects(P1, [ProviderAvailabilityRule(provider_id=P1)]) == []
        assert mock_delete.mock_calls == []

    def test_holds_off_stops_refresh_and_drawing(self):
        from provider_availability.engine.event_sync import _build_hold_block_events, build_provider_hold_refresh_effects

        settings.set_feature("holds", False)
        hold = RecurringBlock(provider_id=P1, hold_type="same_day")
        with patch("provider_availability.engine.event_sync.get_admin_calendars") as mock_cals:
            assert build_provider_hold_refresh_effects(P1, [hold]) == []
            assert _build_hold_block_events(hold) == []
        assert mock_cals.mock_calls == []

    def test_overrides_keep_or_stop(self):
        rule = ProviderAvailabilityRule(provider_id=P1, date_overrides=[DateOverride(date=dt.date(2026, 11, 26), is_closed=True)])
        assert settings.applied_overrides(rule) == rule.date_overrides
        settings.set_feature("overrides", False, keep_existing_overrides=True)
        assert settings.applied_overrides(rule) == rule.date_overrides
        settings.set_feature("overrides", False, keep_existing_overrides=False)
        assert settings.applied_overrides(rule) == []
        settings.set_feature("overrides", True)
        assert settings.applied_overrides(rule) == rule.date_overrides

    def test_provider_timezones_off_uses_the_practice_timezone(self):
        from zoneinfo import ZoneInfo

        from provider_availability.engine import tz_utils

        with patch.object(tz_utils, "get_provider_timezone", return_value="US/Pacific"), \
             patch.object(tz_utils, "get_practice_timezone", return_value="US/Eastern"):
            assert tz_utils.provider_tz(P1) == ZoneInfo("US/Pacific")
            settings.set_feature("provider_timezones", False)
            assert tz_utils.provider_tz(P1) == ZoneInfo("US/Eastern")


@pytest.fixture
def one_provider():
    with patch(f"{MOD}.get_all_rules", return_value=[ProviderAvailabilityRule(provider_id=P1)]), \
         patch(f"{MOD}.get_all_blocks", return_value=[]), \
         patch(f"{MOD}.get_all_recurring_blocks", return_value=[]), \
         patch(f"{MOD}.get_admin_calendars", return_value=[MagicMock(id="cal1")]), \
         patch(f"{MOD}.get_provider_displays", return_value={P1: {"name": "Pat One"}}), \
         patch(f"{MOD}.to_provider_naive", side_effect=lambda d, pid: d.replace(tzinfo=None)):
        yield


class TestAffectedItems:
    def test_buffers_before_and_after(self, one_provider):
        appt = dt.datetime(2026, 10, 15, 14, 0, tzinfo=dt.UTC)
        events = _QS([
            _evt("e1", appt - dt.timedelta(minutes=15), appt),
            _evt("e2", appt + dt.timedelta(minutes=30), appt + dt.timedelta(minutes=45)),
        ])
        with patch(f"{MOD}.EventModel") as ev, patch(f"{MOD}.Appointment") as ap:
            ev.objects.filter.return_value = events
            ap.objects.filter.return_value = _QS([appt])
            result = features.affected_items("buffers", NOW)
        assert result["total"] == 2
        assert result["columns"] == ["Date", "Appointment", "Buffer"]
        assert result["providers"] == [{
            "provider_id": P1, "name": "Pat One", "count": 2,
            "rows": [["Thu Oct 15", "2:00 PM", "15 min before"], ["Thu Oct 15", "2:30 PM", "15 min after"]],
        }]

    def test_holds_show_their_type(self, one_provider):
        start = dt.datetime(2026, 10, 16, 15, 0, tzinfo=dt.UTC)
        with patch(f"{MOD}.EventModel") as ev:
            ev.objects.filter.return_value = _QS([_evt("h1", start, start + dt.timedelta(hours=2), "Next Day Hold")])
            result = features.affected_items("holds", NOW)
        assert result["providers"][0]["rows"] == [["Fri Oct 16", "3:00 PM – 5:00 PM", "Next-day"]]

    def test_overrides_list_upcoming_dates_only(self, one_provider):
        rule = ProviderAvailabilityRule(provider_id=P1, date_overrides=[
            DateOverride(date=dt.date(2026, 11, 26), is_closed=True, reason="Thanksgiving"),
            DateOverride(date=dt.date(2026, 10, 1), is_closed=True),
            DateOverride(date=dt.date(2026, 12, 24), time_windows=[TimeWindow(start=dt.time(8), end=dt.time(12))]),
        ])
        with patch(f"{MOD}.get_rules_for_provider", return_value=[rule]):
            result = features.affected_items("overrides", NOW)
        assert result["providers"][0]["rows"] == [
            ["Thu Nov 26", "Closed", "Thanksgiving"],
            ["Thu Dec 24", "8:00 AM – 12:00 PM", ""],
        ]

    def test_timezones_list_providers_who_would_move(self):
        with patch(f"{MOD}.get_all_provider_timezones", return_value={P1: "US/Pacific", "x" * 32: "US/Eastern"}), \
             patch(f"{MOD}.get_practice_timezone", return_value="US/Eastern"), \
             patch(f"{MOD}.get_provider_displays", return_value={P1: {"name": "Pat One"}}):
            result = features.affected_items("provider_timezones", NOW)
        assert result["total"] == 1
        assert result["providers"][0]["rows"] == [["US/Pacific", "US/Eastern"]]

    def test_rows_stop_at_the_cap_but_the_count_is_exact(self, one_provider):
        start = dt.datetime(2026, 10, 16, 15, 0, tzinfo=dt.UTC)
        with patch(f"{MOD}.EventModel") as ev, patch.object(features, "MAX_ROWS", 2):
            ev.objects.filter.return_value = _QS([_evt(f"l{i}", start, start + dt.timedelta(hours=1), "Lead Time") for i in range(5)])
            result = features.affected_items("lead_time", NOW)
        assert result["total"] == 5
        assert result["providers"][0]["count"] == 5
        assert len(result["providers"][0]["rows"]) == 2

    def test_unknown_feature(self):
        with pytest.raises(ValueError):
            features.affected_items("rounding", NOW)


class TestApply:
    def test_off_needs_a_valid_choice(self):
        with pytest.raises(ValueError, match="Choose one of"):
            features.apply_feature_change("buffers", False, "")
        assert settings.is_feature_on("buffers") is True

    def test_keep_changes_nothing_on_calendars(self, one_provider):
        assert features.apply_feature_change("buffers", False, "keep") == []
        assert settings.is_feature_on("buffers") is False

    def test_remove_deletes_future_buffers(self, one_provider):
        with patch(f"{MOD}.EventModel") as ev:
            ev.objects.filter.return_value = _QS([_evt("e1", NOW, NOW)])
            effects = features.apply_feature_change("buffers", False, "remove")
        assert len(effects) == 1

    def test_remove_lead_time_uses_the_bulk_delete(self):
        with patch(f"{MOD}.delete_all_lead_time_events", return_value=["d"]) as mock_delete:
            assert features.apply_feature_change("lead_time", False, "remove") == ["d"]
        assert mock_delete.mock_calls == [call()]

    def test_remove_holds(self, one_provider):
        with patch(f"{MOD}._hold_event_ids", return_value=["h1", "h2"]):
            assert len(features.apply_feature_change("holds", False, "remove")) == 2

    def test_holds_back_on_redraws_them(self, one_provider):
        settings.set_feature("holds", False)
        hold = RecurringBlock(provider_id=P1, hold_type="same_day")
        with patch(f"{MOD}.get_all_recurring_blocks", return_value=[hold]), \
             patch(f"{MOD}.build_provider_hold_refresh_effects", return_value=["h"]) as mock_refresh:
            assert features.apply_feature_change("holds", True) == ["h"]
        assert mock_refresh.mock_calls == [call(P1, [hold])]

    def test_stop_overrides_resyncs_providers_with_overrides(self):
        rule = ProviderAvailabilityRule(provider_id=P1, date_overrides=[DateOverride(date=dt.date(2026, 11, 26), is_closed=True)])
        with patch(f"{MOD}.get_all_rules", return_value=[rule, ProviderAvailabilityRule(provider_id="z" * 32)]), \
             patch(f"{MOD}._resync_availability", return_value=["s"]) as mock_resync:
            assert features.apply_feature_change("overrides", False, "stop") == ["s"]
        assert mock_resync.mock_calls == [call([P1])]
        assert settings.overrides_applied() is False

    def test_keep_overrides_resyncs_nothing(self):
        with patch(f"{MOD}._resync_availability") as mock_resync:
            assert features.apply_feature_change("overrides", False, "keep") == []
        assert mock_resync.mock_calls == []
        assert settings.overrides_applied() is True

    def test_timezones_off_redraws_around_the_switch(self):
        blk = AdminBlock(id="b1", provider_id=P1, start=NOW, end=NOW)
        order = []

        def deleted(*a, **k):
            order.append(("delete", settings.is_feature_on("provider_timezones")))
            return ["del"]

        def synced(ids):
            order.append(("sync", settings.is_feature_on("provider_timezones")))
            return ["sync"]

        with patch(f"{MOD}.get_all_provider_timezones", return_value={P1: "US/Pacific"}), \
             patch(f"{MOD}.get_all_blocks", return_value=[blk]), \
             patch(f"{MOD}.get_all_recurring_blocks", return_value=[]), \
             patch(f"{MOD}.build_delete_block_effects", side_effect=deleted), \
             patch(f"{MOD}._resync_availability", side_effect=synced), \
             patch(f"{MOD}.build_recurring_blocks_resync_effects", return_value=[]), \
             patch(f"{MOD}.build_block_event_effects", return_value=["draw"]):
            effects = features.apply_feature_change("provider_timezones", False, "move")
        assert effects == ["del", "sync", "draw"]
        # Old events are deleted while the provider's own timezone still applies, then redrawn in the practice one.
        assert order == [("delete", True), ("sync", False)]
