"""Tests for my_schedule.handlers.access."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from my_schedule.handlers import access
from my_schedule.handlers.access import (
    is_restricted,
    parse_flag,
    parse_list,
    restricted_roles,
    staff_by_user_dbid,
)


def _staff(
    staff_id: str = "staff-1", roles: tuple[str, ...] = ("MD",)
) -> SimpleNamespace:
    role_objs = [SimpleNamespace(internal_code=code) for code in roles]
    return SimpleNamespace(id=staff_id, roles=SimpleNamespace(all=lambda: role_objs))


class TestParseList:
    def test_splits_and_trims(self) -> None:
        assert parse_list(" MD, NP ,,PA ") == {"MD", "NP", "PA"}

    @pytest.mark.parametrize("raw", [None, "", " , "])
    def test_blank_is_empty(self, raw: str | None) -> None:
        assert parse_list(raw) == set()


class TestParseFlag:
    @pytest.mark.parametrize("raw", ["yes", "YES", "true", "1", "on", " Yes "])
    def test_true_values(self, raw: str) -> None:
        assert parse_flag(raw, default=False) is True

    @pytest.mark.parametrize("raw", ["no", "false", "0", "off"])
    def test_false_values(self, raw: str) -> None:
        assert parse_flag(raw, default=True) is False

    @pytest.mark.parametrize("raw", [None, "", "maybe"])
    def test_blank_or_unknown_uses_default(self, raw: str | None) -> None:
        assert parse_flag(raw, default=True) is True
        assert parse_flag(raw, default=False) is False


class TestRestrictedRoles:
    def test_default_when_blank(self) -> None:
        assert restricted_roles({}) == {"MD", "NP", "PA"}
        assert restricted_roles({"RESTRICTED_ROLES": "  "}) == {"MD", "NP", "PA"}

    def test_configured_roles_are_uppercased(self) -> None:
        assert restricted_roles({"RESTRICTED_ROLES": "md, netpharm"}) == {
            "MD",
            "NETPHARM",
        }


class TestIsRestricted:
    def test_no_staff_is_not_restricted(self) -> None:
        assert is_restricted(None, {}) is False

    @pytest.mark.parametrize("role", ["MD", "NP", "PA"])
    def test_default_roles_are_restricted(self, role: str) -> None:
        assert is_restricted(_staff(roles=(role,)), {}) is True

    def test_other_roles_are_not_restricted(self) -> None:
        assert is_restricted(_staff(roles=("CC", "AD")), {}) is False

    def test_any_listed_role_restricts_mixed_roles(self) -> None:
        assert is_restricted(_staff(roles=("AD", "MD")), {}) is True

    def test_role_match_ignores_case(self) -> None:
        assert is_restricted(_staff(roles=("md",)), {}) is True

    def test_custom_role_list_replaces_default(self) -> None:
        secrets = {"RESTRICTED_ROLES": "NetPharm"}
        assert is_restricted(_staff(roles=("MD",)), secrets) is False
        assert is_restricted(_staff(roles=("NETPHARM",)), secrets) is True

    def test_exempt_staff_id_wins(self) -> None:
        secrets = {"EXEMPT_STAFF_IDS": "staff-9, staff-1"}
        assert (
            is_restricted(_staff(staff_id="staff-1", roles=("MD",)), secrets) is False
        )
        assert is_restricted(_staff(staff_id="staff-2", roles=("MD",)), secrets) is True

    def test_no_roles_is_not_restricted(self) -> None:
        assert is_restricted(_staff(roles=()), {}) is False


class TestStaffLookups:
    @pytest.mark.parametrize("raw", [None, "", "abc"])
    def test_staff_by_user_dbid_rejects_bad_ids(self, raw: str | None) -> None:
        with patch.object(access, "Staff") as staff_model:
            assert staff_by_user_dbid(raw) is None
        staff_model.objects.filter.assert_not_called()

    def test_staff_by_user_dbid_filters_active(self) -> None:
        with patch.object(access, "Staff") as staff_model:
            first = staff_model.objects.filter.return_value.prefetch_related.return_value.first
            first.return_value = "staff"
            assert staff_by_user_dbid("42") == "staff"
        staff_model.objects.filter.assert_called_once_with(user__dbid=42, active=True)
