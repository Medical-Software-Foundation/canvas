"""Settings endpoints (rule defaults, access control, editing groups) and access-aware reads."""

from http import HTTPStatus
from unittest.mock import call, patch

import pytest

from provider_availability.engine import facilities, settings
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


FAC_A = "0d3c9f4e-5a2b-4c8d-9e1f-123456789abc"
FAC_B = "11111111-2222-3333-4444-555555555555"
FACILITIES = [{"id": FAC_A, "name": "Apple Valley Care"}, {"id": FAC_B, "name": "Pine Ridge Rehabilitation"}]


def _handler(staff_id=ADMIN, json_body=None, path_params=None):
    return _make_handler(staff_id=staff_id, json_body=json_body, path_params=path_params, secrets=SECRETS)


@pytest.fixture(autouse=True)
def lookups():
    with patch(f"{MODULE}.get_staff_directory", return_value=STAFF), \
         patch(f"{MODULE}.get_teams", return_value=[{"id": TEAM, "name": "Admins"}]), \
         patch(f"{MODULE}.get_active_locations", return_value=[{"id": "loc1", "name": "Boise"}]), \
         patch(f"{MODULE}.get_active_facilities", return_value=FACILITIES), \
         patch("provider_availability.engine.facilities.get_active_facilities", return_value=FACILITIES), \
         patch(f"{MODULE}.get_schedulable_provider_ids", return_value=set()):
        yield


class TestGetSettings:
    def test_settings_still_load_when_the_role_lookup_fails(self):
        with patch(f"{MODULE}.get_schedulable_provider_ids", side_effect=RuntimeError("roles")):
            data, code = _parse(_handler().get_settings()[0])
        assert code == HTTPStatus.OK
        assert data["provider_facilities"] == {}

    def test_admin_gets_everything(self):
        data, code = _parse(_handler().get_settings()[0])
        assert code == HTTPStatus.OK
        assert data["features"]["buffers"] is True
        assert data["rule_defaults"] == {"buffer_pre": 0, "buffer_post": 0, "min_lead_hours": 0}
        assert data["access"]["default_access"] == "none"  # the secret restricts access and nothing is saved
        assert data["admins"] == [{"id": ADMIN, "name": "Ada Admin"}]
        assert data["admins_from"] == "secret"
        assert data["secret_admins"] == [ADMIN]
        assert data["teams"] == [{"id": TEAM, "name": "Admins"}]
        assert len(data["staff"]) == 4
        assert data["facilities"] == FACILITIES
        assert data["provider_facilities"] == {}

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
    @pytest.fixture(autouse=True)
    def team_members(self):
        with patch("provider_availability.engine.access.Team") as team:
            team.objects.filter.return_value.values_list.return_value = [SCHED]
            yield team

    def test_admins_and_default(self):
        body = {"admin_team_ids": [TEAM], "admin_staff_ids": [PROV1], "default_access": "view"}
        data, code = _parse(_handler(json_body=body).put_access()[0])
        assert code == HTTPStatus.OK
        assert data["access"]["admin_team_ids"] == [TEAM]
        assert data["access"]["admin_staff_ids"] == [PROV1]
        assert data["access"]["default_access"] == "view"

    def test_unknown_team_is_rejected(self):
        data, code = _parse(_handler(json_body={"admin_team_ids": ["nope"]}).put_access()[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert settings.get_access_config()["admin_team_ids"] == []

    def test_inactive_admin_is_rejected(self):
        data, code = _parse(_handler(json_body={"admin_staff_ids": ["z" * 32]}).put_access()[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "active" in data["error"]

    def test_admins_must_be_lists(self):
        _, code = _parse(_handler(json_body={"admin_team_ids": TEAM}).put_access()[0])
        assert code == HTTPStatus.BAD_REQUEST

    def test_clearing_the_admins(self):
        settings.set_admins([TEAM], [PROV1])
        _parse(_handler(json_body={"admin_team_ids": [], "admin_staff_ids": []}).put_access()[0])
        config = settings.get_access_config()
        assert (config["admin_team_ids"], config["admin_staff_ids"]) == ([], [])

    def test_cannot_save_admins_that_leave_you_out(self):
        # SCHED is an admin only through their team; dropping the team would lock them out.
        settings.set_admins([TEAM], [])
        handler = _make_handler(staff_id=SCHED, json_body={"admin_team_ids": [], "admin_staff_ids": [PROV1]}, secrets={})
        data, code = _parse(handler.put_access()[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "lock you out" in data["error"]
        assert settings.get_access_config()["admin_team_ids"] == [TEAM]

    def test_the_secret_keeps_its_admins_in(self):
        # ADMIN is in the plugin secret, so saving admins without them still leaves them an admin.
        data, code = _parse(_handler(json_body={"admin_team_ids": [], "admin_staff_ids": [PROV1]}).put_access()[0])
        assert code == HTTPStatus.OK
        assert data["access"]["admin_staff_ids"] == [PROV1]

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


class TestProviderFacilities:
    @pytest.fixture(autouse=True)
    def schedulable(self):
        with patch(f"{MODULE}.get_schedulable_provider_ids", return_value={"prov-1"}):
            yield

    def test_saves_a_providers_facilities(self):
        body = {"provider_id": "prov-1", "facility_ids": [FAC_B, FAC_A, FAC_B]}
        data, code = _parse(_handler(json_body=body).put_provider_facilities()[0])
        assert code == HTTPStatus.OK
        assert data == {"provider_id": "prov-1", "facility_ids": [FAC_B, FAC_A]}
        assert facilities.get_provider_facilities() == {"prov-1": [FAC_B, FAC_A]}

    def test_an_empty_list_clears_them(self):
        facilities.set_provider_facilities("prov-1", [FAC_A])
        _, code = _parse(_handler(json_body={"provider_id": "prov-1", "facility_ids": []}).put_provider_facilities()[0])
        assert code == HTTPStatus.OK
        assert facilities.get_provider_facilities() == {}

    def test_unknown_facility_is_a_400(self):
        body = {"provider_id": "prov-1", "facility_ids": ["99999999-2222-3333-4444-555555555555"]}
        data, code = _parse(_handler(json_body=body).put_provider_facilities()[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert data["error"] == "Choose active facilities only."

    def test_each_provider_is_saved_separately(self, settings_cache):
        facilities.set_provider_facilities("prov-1", [FAC_A])
        facilities.set_provider_facilities("prov-2", [FAC_B])
        assert settings_cache.data["pa:provider_facilities:prov-1"] == [FAC_A]
        assert settings_cache.data["pa:provider_facilities:prov-2"] == [FAC_B]
        assert facilities.get_provider_facilities() == {"prov-1": [FAC_A], "prov-2": [FAC_B]}

    def test_a_facility_made_inactive_drops_out_of_reads_and_saves(self, settings_cache):
        gone = "22222222-3333-4444-5555-666666666666"
        settings_cache.data["pa:provider_facilities:prov-1"] = [FAC_A, gone]
        settings_cache.data["pa:provider_facilities_index"] = ["prov-1"]
        assert facilities.get_provider_facilities() == {"prov-1": [FAC_A]}
        # The page still holds the inactive id; saving with it succeeds and drops it.
        body = {"provider_id": "prov-1", "facility_ids": [FAC_A, gone, FAC_B]}
        data, code = _parse(_handler(json_body=body).put_provider_facilities()[0])
        assert (code, data["facility_ids"]) == (HTTPStatus.OK, [FAC_A, FAC_B])

    def test_facilities_saved_before_0_27_move_to_one_key_per_provider(self, settings_cache):
        settings_cache.data["pa:provider_facilities"] = {"prov-1": [FAC_A], "prov-2": []}
        assert facilities.get_provider_facilities() == {"prov-1": [FAC_A]}
        assert "pa:provider_facilities" not in settings_cache.data
        assert settings_cache.data["pa:provider_facilities_index"] == ["prov-1"]

    def test_a_provider_missing_from_the_index_is_still_read_when_passed(self, settings_cache):
        # Two saves at once can each write the index without the other's provider.
        settings_cache.data["pa:provider_facilities:prov-1"] = [FAC_A]
        settings_cache.data["pa:provider_facilities_index"] = []
        assert facilities.get_provider_facilities(provider_ids={"prov-1"}) == {"prov-1": [FAC_A]}
        assert facilities.get_provider_facilities() == {}

    def test_the_background_refresh_keeps_passed_and_indexed_providers_facilities(self, settings_cache):
        settings_cache.data["pa:provider_facilities:prov-1"] = [FAC_A]
        settings_cache.data["pa:provider_facilities:prov-3"] = [FAC_B]
        settings_cache.data["pa:provider_facilities_index"] = ["prov-3"]
        with patch.object(settings_cache, "set", wraps=settings_cache.set) as sets:
            facilities.refresh_provider_facility_ttls(["prov-1", "prov-2"])
        assert sorted(c.args[0] for c in sets.mock_calls) == ["pa:provider_facilities:prov-1", "pa:provider_facilities:prov-3"]

    def test_prefixed_keys_from_the_cache_are_read(self, settings_cache):
        settings_cache.data["pa:provider_facilities_index"] = ["prov-1"]
        with patch.object(settings_cache, "get_many", return_value={"myplugin:pa:provider_facilities:prov-1": [FAC_A]}):
            assert facilities.get_provider_facilities() == {"prov-1": [FAC_A]}

    def test_active_ids_passed_in_skip_the_lookup(self, settings_cache):
        settings_cache.data["pa:provider_facilities:prov-1"] = [FAC_A, FAC_B]
        settings_cache.data["pa:provider_facilities_index"] = ["prov-1"]
        with patch("provider_availability.engine.facilities.get_active_facilities") as lookup:
            assert facilities.get_provider_facilities({FAC_B}) == {"prov-1": [FAC_B]}
        assert lookup.mock_calls == []

    def test_facility_ids_must_be_a_list(self):
        data, code = _parse(_handler(json_body={"provider_id": "prov-1", "facility_ids": FAC_A}).put_provider_facilities()[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "list" in data["error"]

    def test_provider_must_be_schedulable(self):
        data, code = _parse(_handler(json_body={"provider_id": "someone", "facility_ids": []}).put_provider_facilities()[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "provider" in data["error"]

    def test_non_admin_cannot(self):
        body = {"provider_id": "prov-1", "facility_ids": [FAC_A]}
        _, code = _parse(_handler(staff_id=SCHED, json_body=body).put_provider_facilities()[0])
        assert code == HTTPStatus.FORBIDDEN
        assert facilities.get_provider_facilities() == {}

    def test_suggestions(self):
        rows = [{"id": FAC_A, "name": "Apple Valley Care", "patients": 22}]
        with patch(f"{MODULE}.facility_suggestions", return_value=rows) as suggest:
            data, code = _parse(_handler(path_params={"provider_id": "prov-1"}).get_facility_suggestions()[0])
        assert code == HTTPStatus.OK
        assert data == {"provider_id": "prov-1", "suggestions": rows}
        assert suggest.mock_calls == [call("prov-1")]

    def test_suggestions_need_a_schedulable_provider(self):
        with patch(f"{MODULE}.facility_suggestions") as suggest:
            _, code = _parse(_handler(path_params={"provider_id": "someone"}).get_facility_suggestions()[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert suggest.mock_calls == []

    def test_suggestions_are_for_admins(self):
        with patch(f"{MODULE}.facility_suggestions") as suggest:
            _, code = _parse(_handler(staff_id=SCHED, path_params={"provider_id": "prov-1"}).get_facility_suggestions()[0])
        assert code == HTTPStatus.FORBIDDEN
        assert suggest.mock_calls == []
