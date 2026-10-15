"""Practice settings: feature switches, new rule defaults, access config and editing groups."""

import pytest

from provider_availability.engine import settings
from provider_availability.engine.storage import ACCESS_KEY, FEATURES_KEY, RULE_DEFAULTS_KEY


class TestFeatures:
    def test_every_feature_starts_on(self, settings_cache):
        assert settings.get_features() == {
            "buffers": True, "lead_time": True, "holds": True, "overrides": True, "provider_timezones": True,
        }

    def test_turning_one_off_keeps_the_rest(self, settings_cache):
        settings.set_feature("holds", False)
        assert settings.is_feature_on("holds") is False
        assert settings.is_feature_on("buffers") is True
        assert settings_cache.data[FEATURES_KEY]["holds"] is False

    def test_unknown_feature_is_rejected(self, settings_cache):
        with pytest.raises(ValueError, match="Unknown feature"):
            settings.set_feature("rounding", False)

    def test_unknown_stored_keys_are_ignored(self, settings_cache):
        settings_cache.data[FEATURES_KEY] = {"old_switch": False, "buffers": False}
        assert settings.get_features()["buffers"] is False
        assert "old_switch" not in settings.get_features()


class TestRuleDefaults:
    def test_start_at_zero(self, settings_cache):
        assert settings.get_rule_defaults() == {"buffer_pre": 0, "buffer_post": 0, "min_lead_hours": 0}

    def test_saved_values_come_back_as_numbers(self, settings_cache):
        saved = settings.set_rule_defaults({"buffer_pre": "5", "buffer_post": 15, "min_lead_hours": 24})
        assert saved == {"buffer_pre": 5, "buffer_post": 15, "min_lead_hours": 24}
        assert settings.get_rule_defaults() == saved
        assert settings_cache.data[RULE_DEFAULTS_KEY] == saved

    @pytest.mark.parametrize("value", [-1, 10081, "ten", None])
    def test_bad_values_are_rejected(self, settings_cache, value):
        with pytest.raises(ValueError):
            settings.set_rule_defaults({"buffer_pre": value, "buffer_post": 0, "min_lead_hours": 0})
        assert RULE_DEFAULTS_KEY not in settings_cache.data


class TestAccessConfig:
    def test_starts_unsaved(self, settings_cache):
        assert settings.get_access_config() == {
            "admin_team_id": "", "default_access": "full", "default_access_saved": False, "groups": [],
        }

    def test_picking_a_team_does_not_save_a_default_access_level(self, settings_cache):
        settings.set_admin_team(" team-1 ")
        config = settings.get_access_config()
        assert config["admin_team_id"] == "team-1"
        assert config["default_access_saved"] is False
        assert "default_access" not in settings_cache.data[ACCESS_KEY]

    def test_default_access_is_saved_once_chosen(self, settings_cache):
        settings.set_default_access("view")
        config = settings.get_access_config()
        assert config["default_access"] == "view"
        assert config["default_access_saved"] is True

    def test_unknown_default_access_is_rejected(self, settings_cache):
        with pytest.raises(ValueError, match="Default access"):
            settings.set_default_access("everything")


class TestGroups:
    def test_create_edit_delete(self, settings_cache):
        group = settings.save_group(" Orange County ", ["s1", "s1", " s2 "], ["p1"])
        assert group["name"] == "Orange County"
        assert group["schedulers"] == ["s1", "s2"]
        assert settings.get_access_config()["groups"] == [group]

        edited = settings.save_group("Orange County", ["s3"], ["p1", "p2"], group["id"])
        assert edited["id"] == group["id"]
        assert settings.get_access_config()["groups"] == [edited]

        assert settings.delete_group(group["id"]) is True
        assert settings.get_access_config()["groups"] == []
        assert settings.delete_group(group["id"]) is False

    def test_name_is_required_and_unique(self, settings_cache):
        with pytest.raises(ValueError, match="required"):
            settings.save_group("  ", [], [])
        settings.save_group("Idaho", [], [])
        with pytest.raises(ValueError, match="already exists"):
            settings.save_group("idaho", [], [])

    def test_editing_an_unknown_group_is_rejected(self, settings_cache):
        with pytest.raises(ValueError, match="not found"):
            settings.save_group("Boise", [], [], "no-such-id")

    def test_members_must_be_lists(self, settings_cache):
        with pytest.raises(ValueError, match="lists"):
            settings.save_group("Boise", "s1", [])

    def test_saving_a_group_keeps_an_unsaved_default_unsaved(self, settings_cache):
        settings.save_group("Boise", [], [])
        assert settings.get_access_config()["default_access_saved"] is False
