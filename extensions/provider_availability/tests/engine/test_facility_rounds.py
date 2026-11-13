"""Facility rounds: the rule fields, the switch, and how rounds are drawn on calendars."""

import datetime as dt
import json
from datetime import UTC, date
from typing import Any
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from provider_availability.engine import settings
from provider_availability.engine.event_sync import (
    AVAILABILITY_TITLE,
    ROUND_TITLE_PREFIX,
    _build_rule_events,
    round_location_ids,
    round_title,
    sync_provider_availability,
)
from provider_availability.engine.models import ProviderAvailabilityRule, TimeWindow

MODULE = "provider_availability.engine.event_sync"
PROVIDER_ID = "provider-uuid-123"


def _round(**overrides):
    fields: dict[str, Any] = dict(
        id="round-1",
        provider_id=PROVIDER_ID,
        weekly_schedule={"tuesday": [TimeWindow(start=dt.time(8, 0), end=dt.time(12, 0))]},
        facility_id="fac-1",
        facility_name="Apple Valley Care",
        max_visits=10,
        reason="Tuesday rounds",
    )
    fields.update(overrides)
    return ProviderAvailabilityRule(**fields)


def _titles(effects):
    return [json.loads(e.payload)["data"]["title"] for e in effects if '"title"' in e.payload]


class TestRoundFields:
    def test_round_round_trips_through_a_dict(self):
        rule = _round()
        back = ProviderAvailabilityRule.from_dict(rule.to_dict())
        assert (back.facility_id, back.facility_name, back.max_visits) == ("fac-1", "Apple Valley Care", 10)
        assert back.is_round is True

    def test_a_rule_without_a_facility_is_not_a_round(self):
        rule = ProviderAvailabilityRule(provider_id=PROVIDER_ID)
        assert rule.is_round is False
        assert rule.to_dict()["facility_id"] == ""
        assert rule.to_dict()["max_visits"] is None

    def test_rules_saved_before_rounds_existed_still_load(self):
        old = _round().to_dict()
        for key in ("facility_id", "facility_name", "max_visits"):
            old.pop(key)
        rule = ProviderAvailabilityRule.from_dict(old)
        assert (rule.facility_id, rule.facility_name, rule.max_visits, rule.is_round) == ("", "", None, False)

    @pytest.mark.parametrize("raw, expected", [
        (None, None), ("", None), (0, None), (-3, None), ("abc", None), ("8", 8), (6, 6),
    ])
    def test_visit_limit_is_a_whole_number_above_zero_or_none(self, raw, expected):
        data = _round().to_dict()
        data["max_visits"] = raw
        assert ProviderAvailabilityRule.from_dict(data).max_visits == expected


class TestRoundsSwitch:
    def test_off_until_turned_on(self, settings_cache):
        assert settings.is_feature_on("facility_rounds") is False
        assert settings.rounds_drawn() is False
        settings.set_feature("facility_rounds", True)
        assert settings.is_feature_on("facility_rounds") is True
        assert settings.rounds_drawn() is True

    def test_turning_off_and_keeping_leaves_saved_rounds_drawn(self, settings_cache):
        settings.set_feature("facility_rounds", True)
        settings.set_feature("facility_rounds", False, keep_existing_overrides=True)
        assert settings.is_feature_on("facility_rounds") is False
        assert settings.rounds_drawn() is True

    def test_turning_off_and_removing_takes_rounds_off_calendars(self, settings_cache):
        settings.set_feature("facility_rounds", True)
        settings.set_feature("facility_rounds", False, keep_existing_overrides=False)
        assert settings.rounds_drawn() is False

    def test_the_other_features_are_unaffected(self, settings_cache):
        settings.set_feature("facility_rounds", True)
        assert settings.get_features()["buffers"] is True


class TestDrawingRounds:
    def test_round_title_names_the_facility(self):
        assert round_title(_round()) == ROUND_TITLE_PREFIX + "Apple Valley Care"
        assert round_title(_round(facility_name="")) == ROUND_TITLE_PREFIX + "Facility"

    @patch(f"{MODULE}.round_location_ids", return_value=["primary-loc"])
    @patch(f"{MODULE}.resolve_provider_name", return_value="Dr X")
    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz", return_value=ZoneInfo("US/Pacific"))
    @patch(f"{MODULE}._get_calendar_id", return_value=("cal-primary", []))
    def test_a_round_books_under_the_primary_location_with_the_facility_title(
        self, mock_get_cal, _tz, _loc, _utc, _name, mock_round_locs
    ):
        # The rule's own locations are ignored: a round books where the provider is based.
        rule = _round(location_ids=["some-other-loc"])
        with patch(f"{MODULE}.date") as mock_date:
            mock_date.today.return_value = date(2026, 11, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            effects = _build_rule_events(rule)

        assert mock_round_locs.call_args_list[0].args == (PROVIDER_ID,)
        assert [c.args[1] for c in mock_get_cal.call_args_list] == ["primary-loc"]
        assert _titles(effects) == [ROUND_TITLE_PREFIX + "Apple Valley Care"]

    @patch(f"{MODULE}.round_location_ids", return_value=[])
    def test_a_round_with_nowhere_to_book_draws_nothing(self, _locs):
        assert _build_rule_events(_round()) == []

    @patch(f"{MODULE}.resolve_provider_name", return_value="Dr X")
    @patch(f"{MODULE}.to_utc", side_effect=lambda x: x)
    @patch(f"{MODULE}.localize_naive", side_effect=lambda x, tz: x.replace(tzinfo=UTC))
    @patch(f"{MODULE}.provider_tz", return_value=ZoneInfo("US/Pacific"))
    @patch(f"{MODULE}._get_calendar_id", return_value=("cal-1", []))
    def test_clinic_availability_keeps_the_available_title(self, *_mocks):
        rule = _round(facility_id="", facility_name="", max_visits=None, location_ids=["loc-1"])
        with patch(f"{MODULE}.date") as mock_date:
            mock_date.today.return_value = date(2026, 11, 2)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            effects = _build_rule_events(rule)
        assert _titles(effects) == [AVAILABILITY_TITLE]


class TestRoundLocation:
    def test_primary_practice_location(self):
        with patch(f"{MODULE}.Staff.objects") as staff, patch(f"{MODULE}.PracticeLocation.objects") as locs:
            staff.filter.return_value.values_list.return_value.first.return_value = "primary-loc"
            assert round_location_ids(PROVIDER_ID) == ["primary-loc"]
            assert locs.mock_calls == []

    def test_falls_back_to_the_first_active_location(self):
        with patch(f"{MODULE}.Staff.objects") as staff, patch(f"{MODULE}.PracticeLocation.objects") as locs:
            staff.filter.return_value.values_list.return_value.first.return_value = None
            locs.filter.return_value.order_by.return_value.values_list.return_value.first.return_value = "first-loc"
            assert round_location_ids(PROVIDER_ID) == ["first-loc"]
            assert locs.filter.call_args.kwargs == {"active": True}

    def test_no_location_at_all(self):
        with patch(f"{MODULE}.Staff.objects") as staff, patch(f"{MODULE}.PracticeLocation.objects") as locs:
            staff.filter.return_value.values_list.return_value.first.return_value = None
            locs.filter.return_value.order_by.return_value.values_list.return_value.first.return_value = None
            assert round_location_ids(PROVIDER_ID) == []


class TestSyncSkipsRoundsWhenRemoved:
    @patch(f"{MODULE}._build_rule_events", return_value=["drawn"])
    @patch(f"{MODULE}.get_rules_for_provider")
    @patch(f"{MODULE}.build_delete_effects", return_value=[])
    def test_rounds_are_skipped_once_removed_but_clinic_hours_still_draw(
        self, _delete, mock_rules, mock_build, settings_cache
    ):
        clinic = _round(id="clinic-1", facility_id="", facility_name="", location_ids=["loc-1"])
        mock_rules.return_value = [_round(), clinic]
        settings.set_feature("facility_rounds", False, keep_existing_overrides=False)

        sync_provider_availability(PROVIDER_ID, schedulable_ids={PROVIDER_ID})

        assert [c.args[0].id for c in mock_build.call_args_list] == ["clinic-1"]

    @patch(f"{MODULE}._build_rule_events", return_value=["drawn"])
    @patch(f"{MODULE}.get_rules_for_provider")
    @patch(f"{MODULE}.build_delete_effects", return_value=[])
    def test_rounds_draw_while_the_switch_is_on(self, _delete, mock_rules, mock_build, settings_cache):
        mock_rules.return_value = [_round()]
        settings.set_feature("facility_rounds", True)

        sync_provider_availability(PROVIDER_ID, schedulable_ids={PROVIDER_ID})

        assert [c.args[0].id for c in mock_build.call_args_list] == ["round-1"]


FEATURES_MODULE = "provider_availability.engine.features"


class TestRoundsSwitchOffFlow:
    def test_affected_items_lists_each_active_round(self, settings_cache):
        from provider_availability.engine.features import affected_items

        rounds = [_round(), _round(id="round-2", facility_name="Cedar Hollow", max_visits=None, is_active=True)]
        inactive = _round(id="round-3", is_active=False)
        clinic = _round(id="clinic-1", facility_id="", facility_name="")
        with patch(f"{FEATURES_MODULE}._providers_with_schedules", return_value=[PROVIDER_ID]), \
             patch(f"{FEATURES_MODULE}.get_rules_for_provider", return_value=[*rounds, inactive, clinic]), \
             patch(f"{FEATURES_MODULE}.get_provider_displays", return_value={PROVIDER_ID: {"name": "Dana Whitfield"}}):
            result = affected_items("facility_rounds")

        assert result["columns"] == ["Facility", "Days", "Visits per round"]
        assert result["total"] == 2
        assert result["providers"][0]["rows"] == [
            ["Apple Valley Care", "Tue", "Up to 10"],
            ["Cedar Hollow", "Tue", "No limit"],
        ]

    def test_removing_redraws_every_provider_with_a_round(self, settings_cache):
        from provider_availability.engine.features import apply_feature_change

        settings.set_feature("facility_rounds", True)
        rules = [_round(), _round(id="clinic-1", provider_id="other", facility_id="", facility_name="")]
        with patch(f"{FEATURES_MODULE}.get_all_rules", return_value=rules), \
             patch(f"{FEATURES_MODULE}._resync_availability", return_value=["redraw"]) as resync, \
             patch(f"{FEATURES_MODULE}.refresh_round_limits", return_value=["unblock"]) as refresh:
            effects = apply_feature_change("facility_rounds", False, "remove")

        assert effects == ["redraw", "unblock"]
        assert refresh.call_args_list[0].args == (PROVIDER_ID,)
        assert resync.call_args.args == ([PROVIDER_ID],)
        assert settings.rounds_drawn() is False

    def test_keeping_changes_no_calendars(self, settings_cache):
        from provider_availability.engine.features import apply_feature_change

        settings.set_feature("facility_rounds", True)
        with patch(f"{FEATURES_MODULE}._resync_availability") as resync:
            effects = apply_feature_change("facility_rounds", False, "keep")

        assert effects == []
        assert resync.mock_calls == []
        assert settings.rounds_drawn() is True

    def test_off_needs_keep_or_remove(self, settings_cache):
        from provider_availability.engine.features import apply_feature_change

        with pytest.raises(ValueError, match="keep, remove"):
            apply_feature_change("facility_rounds", False, "")
