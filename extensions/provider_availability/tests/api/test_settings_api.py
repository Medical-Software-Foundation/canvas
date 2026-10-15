"""Settings endpoints (rule defaults, access control, editing groups) and access-aware reads."""

from http import HTTPStatus
from unittest.mock import call, patch

import pytest

from provider_availability.engine import settings
from provider_availability.engine.models import ProviderAvailabilityRule
from tests.api.test_availability_api import MODULE, _make_handler, _parse

ADMIN = "a" * 32
SCHED = "b" * 32
PROV1 = "c" * 32
PROV2 = "d" * 32
TEAM = "12345678-1234-1234-1234-123456789abc"
SECRETS = {"allowed-staff-keys": ADMIN}
STAFF = [
    {"id": ADMIN, "name": "Ada Admin", "location_id": "loc1"},
    {"id": SCHED, "name": "Sam Scheduler", "location_id": "loc1"},
    {"id": PROV1, "name": "Pat One", "location_id": "loc2"},
    {"id": PROV2, "name": "Pia Two", "location_id": ""},
]


def _handler(staff_id=ADMIN, json_body=None, path_params=None):
    return _make_handler(staff_id=staff_id, json_body=json_body, path_params=path_params, secrets=SECRETS)


@pytest.fixture(autouse=True)
def lookups():
    with patch(f"{MODULE}.get_staff_directory", return_value=STAFF), \
         patch(f"{MODULE}.get_teams", return_value=[{"id": TEAM, "name": "Admins"}]), \
         patch(f"{MODULE}.get_active_locations", return_value=[{"id": "loc1", "name": "Boise"}]):
        yield


class TestGetSettings:
    def test_admin_gets_everything(self):
        data, code = _parse(_handler().get_settings()[0])
        assert code == HTTPStatus.OK
        assert data["features"]["buffers"] is True
        assert data["rule_defaults"] == {"buffer_pre": 0, "buffer_post": 0, "min_lead_hours": 0}
        assert data["access"]["default_access"] == "none"  # the secret restricts access and nothing is saved
        assert data["admins"] == [{"id": ADMIN, "name": "Ada Admin"}]
        assert data["admins_from"] == "secret"
        assert data["teams"] == [{"id": TEAM, "name": "Admins"}]
        assert len(data["staff"]) == 4

    def test_not_for_non_admins(self):
        data, code = _parse(_handler(staff_id=SCHED).get_settings()[0])
        assert code == HTTPStatus.FORBIDDEN
        assert "admins" in data["error"]


class TestRuleDefaults:
    def test_saves(self):
        body = {"buffer_pre": 5, "buffer_post": 10, "min_lead_hours": 2}
        data, code = _parse(_handler(json_body=body).put_rule_defaults()[0])
        assert code == HTTPStatus.OK
        assert data["rule_defaults"] == body
        assert settings.get_rule_defaults() == body

    def test_bad_value_is_a_400(self):
        data, code = _parse(_handler(json_body={"buffer_pre": -5}).put_rule_defaults()[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "between" in data["error"]

    def test_non_admin_cannot(self):
        _, code = _parse(_handler(staff_id=SCHED, json_body={"buffer_pre": 5}).put_rule_defaults()[0])
        assert code == HTTPStatus.FORBIDDEN
        assert settings.get_rule_defaults()["buffer_pre"] == 0


class TestAccess:
    def test_team_and_default(self):
        data, code = _parse(_handler(json_body={"admin_team_id": TEAM, "default_access": "view"}).put_access()[0])
        assert code == HTTPStatus.OK
        assert data["access"]["admin_team_id"] == TEAM
        assert data["access"]["default_access"] == "view"

    def test_unknown_team_is_rejected(self):
        data, code = _parse(_handler(json_body={"admin_team_id": "nope"}).put_access()[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert settings.get_access_config()["admin_team_id"] == ""

    def test_clearing_the_team(self):
        settings.set_admin_team(TEAM)
        _parse(_handler(json_body={"admin_team_id": ""}).put_access()[0])
        assert settings.get_access_config()["admin_team_id"] == ""

    def test_bad_level(self):
        _, code = _parse(_handler(json_body={"default_access": "all"}).put_access()[0])
        assert code == HTTPStatus.BAD_REQUEST

    def test_non_admin_cannot(self):
        _, code = _parse(_handler(staff_id=SCHED, json_body={"default_access": "full"}).put_access()[0])
        assert code == HTTPStatus.FORBIDDEN


class TestGroups:
    def test_create_edit_delete(self):
        body = {"name": "Orange County", "schedulers": [SCHED], "providers": [PROV1]}
        data, code = _parse(_handler(json_body=body).post_group()[0])
        assert code == HTTPStatus.OK
        group_id = data["group"]["id"]

        body["providers"] = [PROV1, PROV2]
        data, code = _parse(_handler(json_body=body, path_params={"group_id": group_id}).put_group()[0])
        assert code == HTTPStatus.OK
        assert data["access"]["groups"][0]["providers"] == [PROV1, PROV2]

        data, code = _parse(_handler(path_params={"group_id": group_id}).remove_group()[0])
        assert code == HTTPStatus.OK
        assert data["access"]["groups"] == []

        _, code = _parse(_handler(path_params={"group_id": group_id}).remove_group()[0])
        assert code == HTTPStatus.NOT_FOUND

    def test_inactive_staff_are_rejected(self):
        body = {"name": "Boise", "schedulers": ["f" * 32], "providers": []}
        data, code = _parse(_handler(json_body=body).post_group()[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "not active" in data["error"]
        assert settings.get_access_config()["groups"] == []

    def test_members_must_be_lists(self):
        _, code = _parse(_handler(json_body={"name": "Boise", "schedulers": SCHED}).post_group()[0])
        assert code == HTTPStatus.BAD_REQUEST

    def test_duplicate_name(self):
        settings.save_group("Boise", [], [])
        data, code = _parse(_handler(json_body={"name": "boise"}).post_group()[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "already exists" in data["error"]

    def test_non_admin_cannot(self):
        _, code = _parse(_handler(staff_id=SCHED, json_body={"name": "Boise"}).post_group()[0])
        assert code == HTTPStatus.FORBIDDEN
        assert settings.get_access_config()["groups"] == []


class TestWritesFollowAccess:
    """End to end through the real check: a scheduler edits their group, not anyone else."""

    @pytest.fixture(autouse=True)
    def group(self):
        settings.save_group("Orange County", [SCHED], [PROV1])

    @patch(f"{MODULE}.build_delete_effects", return_value=[])
    @patch(f"{MODULE}.delete_rules_for_provider", return_value=1)
    def test_scheduler_can_change_their_provider(self, mock_delete, mock_effects):
        _, code = _parse(_handler(staff_id=SCHED, path_params={"provider_id": PROV1}).delete_provider_rules()[0])
        assert code == HTTPStatus.OK
        assert mock_delete.mock_calls == [call(PROV1)]

    @patch(f"{MODULE}.delete_rules_for_provider")
    def test_scheduler_cannot_change_someone_outside_their_group(self, mock_delete):
        data, code = _parse(_handler(staff_id=SCHED, path_params={"provider_id": PROV2}).delete_provider_rules()[0])
        assert code == HTTPStatus.FORBIDDEN
        assert "this provider" in data["error"]
        assert mock_delete.mock_calls == []

    @patch(f"{MODULE}.set_practice_timezone")
    def test_practice_timezone_is_admin_only(self, mock_set):
        _, code = _parse(_handler(staff_id=SCHED, json_body={"timezone": "US/Pacific"}).set_timezone()[0])
        assert code == HTTPStatus.FORBIDDEN
        assert mock_set.mock_calls == []


class TestOverviewFollowsAccess:
    @patch(f"{MODULE}.get_provider_displays", side_effect=lambda ids: {i: {"name": i[:4]} for i in ids})
    @patch(f"{MODULE}.get_all_provider_timezones", return_value={})
    @patch(f"{MODULE}.get_practice_timezone", return_value="US/Eastern")
    @patch(f"{MODULE}.get_scheduleable_visit_types", return_value=[])
    @patch(f"{MODULE}.get_all_recurring_blocks", return_value=[])
    @patch(f"{MODULE}.get_all_blocks", return_value=[])
    @patch(f"{MODULE}.get_schedulable_staff")
    @patch(f"{MODULE}.get_all_rules")
    def test_hidden_and_read_only_providers(self, mock_rules, mock_sched, *mocks):
        from tests.api.test_availability_api import _sched

        mock_rules.return_value = [
            ProviderAvailabilityRule(id="r1", provider_id=PROV1),
            ProviderAvailabilityRule(id="r2", provider_id=PROV2),
        ]
        mock_sched.return_value = _sched(PROV1, PROV2)
        settings.save_group("Orange County", [SCHED], [PROV1])

        settings.set_default_access("view")
        data, _ = _parse(_handler(staff_id=SCHED).get_overview()[0])
        assert {p["provider_id"]: p["can_edit"] for p in data["providers"]} == {PROV1: True, PROV2: False}

        settings.set_default_access("none")
        data, _ = _parse(_handler(staff_id=SCHED).get_overview()[0])
        assert [p["provider_id"] for p in data["providers"]] == [PROV1]


class TestFeatureEndpoints:
    @patch(f"{MODULE}.apply_feature_change", return_value=["effect"])
    def test_turn_off_with_a_choice(self, mock_apply):
        result = _handler(json_body={"feature": "buffers", "on": False, "choice": "remove"}).put_feature()
        assert result[0] == "effect"
        data, code = _parse(result[1])
        assert code == HTTPStatus.OK
        assert data["changed"] == 1
        assert mock_apply.mock_calls == [call("buffers", False, "remove")]

    def test_on_must_be_a_boolean(self):
        data, code = _parse(_handler(json_body={"feature": "buffers", "on": "no"}).put_feature()[0])
        assert code == HTTPStatus.BAD_REQUEST

    def test_missing_choice_is_a_400(self):
        data, code = _parse(_handler(json_body={"feature": "buffers", "on": False}).put_feature()[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "Choose one of" in data["error"]

    def test_non_admin_cannot(self):
        _, code = _parse(_handler(staff_id=SCHED, json_body={"feature": "buffers", "on": False, "choice": "keep"}).put_feature()[0])
        assert code == HTTPStatus.FORBIDDEN
        assert settings.is_feature_on("buffers") is True

    @patch(f"{MODULE}.affected_items", return_value={"total": 0, "providers": []})
    def test_affected(self, mock_items):
        data, code = _parse(_handler(path_params={"feature": "holds"}).get_affected()[0])
        assert code == HTTPStatus.OK
        assert mock_items.mock_calls == [call("holds")]

    def test_affected_unknown_feature(self):
        _, code = _parse(_handler(path_params={"feature": "rounding"}).get_affected()[0])
        assert code == HTTPStatus.BAD_REQUEST


class TestSwitchedOffFeaturesRefuseNewData:
    def test_no_new_holds(self):
        settings.set_feature("holds", False)
        body = {"provider_id": PROV1, "hold_type": "same_day", "weekly_schedule": {}}
        data, code = _parse(_handler(json_body=body).create_recurring_block()[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "Holds are turned off" in data["error"]

    def test_no_new_overrides(self):
        settings.set_feature("overrides", False)
        data, code = _parse(_handler(path_params={"provider_id": PROV1, "rule_id": "r1"}).add_override()[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "Date overrides are turned off" in data["error"]

    def test_no_provider_timezones(self):
        settings.set_feature("provider_timezones", False)
        data, code = _parse(_handler(json_body={"provider_id": PROV1, "timezone": "US/Pacific"}).set_provider_tz()[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "Provider timezones are turned off" in data["error"]
