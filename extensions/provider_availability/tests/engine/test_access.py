"""Who can view and edit whose availability (engine.access)."""

from unittest.mock import call, patch

import pytest

from provider_availability.engine import settings
from provider_availability.engine.access import Access, admin_ids, effective_default_access, team_member_ids

ADMIN = "a" * 32
SCHED = "b" * 32
PROV1 = "c" * 32
PROV2 = "d" * 32
OTHER = "e" * 32
TEAM = "12345678-1234-1234-1234-123456789abc"


class _Members(list):
    def values_list(self, *fields, flat=False):
        return self


@pytest.fixture
def team_members():
    with patch("provider_availability.engine.access.Team") as team:
        team.objects.filter.return_value = _Members([ADMIN])
        yield team


class TestAdmins:
    def test_nobody_configured_means_everyone_is_admin(self, settings_cache):
        assert admin_ids({}) == set()
        assert Access.for_staff(OTHER, {}).is_admin is True

    def test_secret_lists_admins(self, settings_cache):
        secrets = {"allowed-staff-keys": f"{ADMIN}, "}
        assert Access.for_staff(ADMIN, secrets).is_admin is True
        assert Access.for_staff(OTHER, secrets).is_admin is False

    def test_team_replaces_the_secret(self, settings_cache, team_members):
        settings.set_admin_team(TEAM)
        secrets = {"allowed-staff-keys": OTHER}
        assert Access.for_staff(ADMIN, secrets).is_admin is True
        assert Access.for_staff(OTHER, secrets).is_admin is False
        assert team_members.objects.filter.mock_calls == [call(id=TEAM), call(id=TEAM)]

    def test_empty_team_falls_back_to_the_secret(self, settings_cache, team_members):
        team_members.objects.filter.return_value = _Members([])
        settings.set_admin_team(TEAM)
        assert admin_ids({"allowed-staff-keys": OTHER}) == {OTHER}

    def test_malformed_team_id_is_never_queried(self, settings_cache, team_members):
        assert team_member_ids("not-a-uuid") == set()
        assert team_member_ids("") == set()
        assert team_members.objects.filter.mock_calls == []


class TestDefaultAccess:
    def test_starts_full_without_the_secret(self, settings_cache):
        assert effective_default_access({}) == "full"

    def test_starts_none_when_the_secret_restricts_access(self, settings_cache):
        """Staff the secret left out must not gain access when this ships."""
        assert effective_default_access({"allowed-staff-keys": ADMIN}) == "none"
        access = Access.for_staff(OTHER, {"allowed-staff-keys": ADMIN})
        assert access.can_edit(PROV1) is False
        assert access.can_view(PROV1) is False
        assert access.can_edit(OTHER) is True

    def test_a_saved_level_wins(self, settings_cache):
        settings.set_default_access("view")
        assert effective_default_access({"allowed-staff-keys": ADMIN}) == "view"

    @pytest.mark.parametrize("level,edit,view", [("full", True, True), ("view", False, True), ("none", False, False)])
    def test_staff_outside_groups_follow_the_default(self, settings_cache, level, edit, view):
        settings.set_default_access(level)
        access = Access.for_staff(OTHER, {"allowed-staff-keys": ADMIN})
        assert access.can_edit(PROV1) is edit
        assert access.can_view(PROV1) is view


class TestGroups:
    @pytest.fixture
    def grouped(self, settings_cache):
        settings.save_group("Orange County", [SCHED], [PROV1])
        return {"allowed-staff-keys": ADMIN}

    def test_scheduler_edits_only_their_group_even_with_full_default(self, grouped):
        settings.set_default_access("full")
        access = Access.for_staff(SCHED, grouped)
        assert access.can_edit(PROV1) is True
        assert access.can_edit(PROV2) is False
        assert access.can_view(PROV2) is True

    def test_scheduler_sees_only_their_group_with_no_access_default(self, grouped):
        settings.set_default_access("none")
        access = Access.for_staff(SCHED, grouped)
        assert access.can_view(PROV1) is True
        assert access.can_view(PROV2) is False

    def test_providers_always_edit_their_own(self, grouped):
        settings.set_default_access("none")
        assert Access.for_staff(PROV2, grouped).can_edit(PROV2) is True

    def test_two_groups_add_up(self, grouped):
        settings.save_group("Idaho", [SCHED], [PROV2])
        access = Access.for_staff(SCHED, grouped)
        assert access.can_edit_all([PROV1, PROV2]) is True

    def test_admins_ignore_groups(self, grouped):
        assert Access.for_staff(ADMIN, grouped).can_edit(PROV2) is True

    def test_dashed_ids_match(self, grouped):
        dashed = f"{PROV1[:8]}-{PROV1[8:12]}-{PROV1[12:16]}-{PROV1[16:20]}-{PROV1[20:]}"
        assert Access.for_staff(SCHED, grouped).can_edit(dashed) is True


def test_nobody_signed_in_can_do_nothing(settings_cache):
    access = Access.for_staff("", {})
    assert access.can_edit(PROV1) is False
    assert access.can_view(PROV1) is False


def test_summary(settings_cache):
    settings.save_group("Orange County", [SCHED], [PROV1])
    assert Access.for_staff(SCHED, {"allowed-staff-keys": ADMIN}).summary() == {
        "staff_id": SCHED, "is_admin": False, "in_group": True, "group_providers": [PROV1], "default_access": "none",
    }
