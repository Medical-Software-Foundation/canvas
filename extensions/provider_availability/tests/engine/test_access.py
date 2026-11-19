"""Who can view and edit whose availability (engine.access)."""

from unittest.mock import call, patch

import pytest

from provider_availability.engine import settings
from provider_availability.engine.access import (
    CANVAS_SUPPORT_KEY,
    Access,
    active_staff_ids,
    admin_ids,
    effective_default_access,
)

ADMIN = "a" * 32
SCHED = "b" * 32
PROV1 = "c" * 32
PROV2 = "d" * 32
OTHER = "e" * 32
TEAM = "12345678-1234-1234-1234-123456789abc"


ROLE = "OFFICE_MGR"


class StaffDirectory:
    """Stands in for the active-staff query: who holds which role, and who is active."""

    def __init__(self, roles=None, inactive=()):
        self.roles = {r: set(m) for r, m in (roles or {}).items()}
        self.inactive = set(inactive)
        self.calls = []

    def __call__(self, codes, people):
        self.calls.append((list(codes), list(people)))
        found = set(people) | {m for c in codes for m in self.roles.get(c, ())}
        return sorted(found - self.inactive)


@pytest.fixture
def directory():
    staff = StaffDirectory({ROLE: {ADMIN}})
    with patch("provider_availability.engine.access._query_active_staff", staff):
        yield staff


class TestAdmins:
    def test_before_setup_everyone_is_admin(self, settings_cache):
        assert admin_ids({}) == set()
        assert Access.for_staff(OTHER, {}).is_admin is True

    def test_secret_lists_admins(self, settings_cache):
        secrets = {"allowed-staff-keys": f"{ADMIN}, "}
        assert Access.for_staff(ADMIN, secrets).is_admin is True
        assert Access.for_staff(OTHER, secrets).is_admin is False

    def test_role_and_secret_both_count(self, settings_cache, directory):
        settings.set_admins([ROLE.lower()], [])
        secrets = {"allowed-staff-keys": OTHER}
        assert Access.for_staff(ADMIN, secrets).is_admin is True
        assert Access.for_staff(OTHER, secrets).is_admin is True
        assert Access.for_staff(SCHED, secrets).is_admin is False
        # Codes are saved upper-cased, as engine.roles compares them.
        assert directory.calls == [([ROLE], [])] * 3

    def test_people_and_roles_add_up(self, settings_cache, directory):
        settings.set_admins([ROLE], [SCHED])
        assert admin_ids({}) == {ADMIN, SCHED}
        assert directory.calls == [([ROLE], [SCHED])]

    def test_after_setup_no_active_admin_means_only_canvas_support(self, settings_cache, directory):
        directory.inactive = {ADMIN, SCHED}
        settings.set_admins([ROLE], [SCHED])
        assert admin_ids({}) == set()
        assert Access.for_staff(OTHER, {}).is_admin is False
        assert Access.for_staff(ADMIN, {}).is_admin is False
        assert Access.for_staff(CANVAS_SUPPORT_KEY, {}).is_admin is True

    def test_saving_no_admins_still_counts_as_set_up(self, settings_cache, directory):
        settings.set_admins([], [])
        assert settings.get_access_config()["admins_saved"] is True
        assert Access.for_staff(OTHER, {}).is_admin is False

    def test_canvas_support_is_always_an_admin(self, settings_cache, directory):
        settings.set_admins([ROLE], [])
        access = Access.for_staff(CANVAS_SUPPORT_KEY, {"allowed-staff-keys": ADMIN})
        assert access.is_admin is True
        assert access.can_edit(PROV1) is True

    def test_malformed_ids_and_blank_codes_are_never_queried(self, settings_cache, directory):
        assert active_staff_ids(["", "  "], ["nope"]) == set()
        assert directory.calls == []


def test_active_staff_query_matches_roles_or_people_and_only_active():
    from django.db.models import Q

    from provider_availability.engine import access

    with patch.object(access, "Staff") as staff:
        staff.objects.filter.return_value.values_list.return_value.distinct.return_value = [ADMIN]
        assert access.active_staff_ids(["office_mgr"], [SCHED]) == {ADMIN}
    ((args, kwargs),) = [c[1:] for c in staff.objects.filter.mock_calls[:1]]
    assert args == ((Q() | Q(roles__internal_code__iexact="OFFICE_MGR")) | Q(id__in=[SCHED]),)
    assert kwargs == {"active": True}


def test_roles_with_active_staff():
    from django.db.models import Q

    from provider_availability.engine import access

    with patch.object(access, "StaffRole") as role:
        role.objects.filter.return_value.values_list.return_value.distinct.return_value = ["office_mgr"]
        assert access.roles_with_active_staff(["OFFICE_MGR", "NURSE"]) == {"OFFICE_MGR"}
        assert access.roles_with_active_staff([]) == set()
    assert role.objects.filter.mock_calls[0] == call(
        Q() | Q(internal_code__iexact="NURSE") | Q(internal_code__iexact="OFFICE_MGR"), staff__active=True
    )


class TestDefaultAccess:
    def test_starts_full_without_the_secret(self, settings_cache):
        assert effective_default_access({}) == "full"

    def test_starts_none_when_the_secret_restricts_access(self, settings_cache):
        """Staff the secret left out must not gain access when this ships."""
        assert effective_default_access({"allowed-staff-keys": ADMIN}) == "none"
        access = Access.for_staff(OTHER, {"allowed-staff-keys": ADMIN})
        assert access.can_edit(PROV1) is False
        assert access.can_view(PROV1) is False
        assert access.can_edit(OTHER) is False
        assert access.can_view(OTHER) is True

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

    @pytest.mark.parametrize("level,edit", [("full", True), ("view", True), ("none", False)])
    def test_providers_edit_their_own_unless_default_is_none(self, grouped, level, edit):
        settings.set_default_access(level)
        access = Access.for_staff(PROV2, grouped)
        assert access.can_edit(PROV2) is edit
        assert access.can_view(PROV2) is True
        assert access.can_view_others() is (level != "none")

    def test_scheduler_outside_their_own_group_follows_the_default_for_themselves(self, grouped):
        settings.set_default_access("none")
        access = Access.for_staff(SCHED, grouped)
        assert access.can_edit(SCHED) is False
        assert access.can_view(SCHED) is True
        settings.save_group("Self", [SCHED], [SCHED])
        assert Access.for_staff(SCHED, grouped).can_edit(SCHED) is True

    def test_no_secret_and_no_saved_admins_keeps_self_edit(self, settings_cache):
        """Before setup everyone is an admin, so nothing changes for a new practice."""
        assert Access.for_staff(PROV2, {}).can_edit(PROV2) is True

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


def test_role_names_include_roles_no_active_staff_hold():
    from provider_availability.engine import access

    with patch.object(access, "StaffRole") as role:
        role.objects.filter.return_value.values_list.return_value = [
            ("office_mgr", "Office Manager"), ("OFFICE_MGR", "Other spelling"), ("NURSE", ""),
        ]
        assert access.role_names(["OFFICE_MGR", "NURSE"]) == {"OFFICE_MGR": "Office Manager"}
        assert access.role_names([]) == {}
    # No staff__active filter: a role whose holders all left still has a name.
    assert "staff__active" not in role.objects.filter.mock_calls[0].kwargs
