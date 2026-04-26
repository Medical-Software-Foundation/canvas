from unittest.mock import MagicMock, call

import pytest

from staff_directory.services.permissions import (
    DEFAULT_ADMIN_ROLE_CODES,
    is_admin,
    parse_admin_role_codes,
)


class TestParseAdminRoleCodes:
    def test_none_returns_defaults(self):
        assert parse_admin_role_codes(None) == DEFAULT_ADMIN_ROLE_CODES

    def test_empty_string_returns_defaults(self):
        assert parse_admin_role_codes("") == DEFAULT_ADMIN_ROLE_CODES

    def test_only_whitespace_returns_defaults(self):
        assert parse_admin_role_codes("   ,  ,") == DEFAULT_ADMIN_ROLE_CODES

    def test_single_code_is_uppercased(self):
        assert parse_admin_role_codes("admin") == ("ADMIN",)

    def test_comma_separated_strips_and_uppercases(self):
        assert parse_admin_role_codes("admin, owner ,  MD ") == ("ADMIN", "OWNER", "MD")


class TestIsAdmin:
    def test_none_staff_returns_false(self):
        assert is_admin(None, ("ADMIN",)) is False

    def test_top_role_matches(self):
        staff = MagicMock()
        staff.top_clinical_role.internal_code = "MD"
        staff.roles.all.return_value = []

        result = is_admin(staff, ("MD", "ADMIN"))

        calls = [
            call.top_clinical_role.internal_code.upper(),
        ]
        # We accept any attribute access; verify the decision is True
        assert result is True

    def test_top_role_matches_case_insensitively(self):
        staff = MagicMock()
        staff.top_clinical_role.internal_code = "admin"

        assert is_admin(staff, ("ADMIN",)) is True

    def test_falls_back_to_roles_manager(self):
        staff = MagicMock()
        staff.top_clinical_role.internal_code = "RN"
        other_role = MagicMock()
        other_role.internal_code = "ADMIN"
        rn_role = MagicMock()
        rn_role.internal_code = "RN"
        staff.roles.all.return_value = [rn_role, other_role]

        assert is_admin(staff, ("ADMIN",)) is True

    def test_no_role_matches_returns_false(self):
        staff = MagicMock()
        staff.top_clinical_role.internal_code = "RN"
        rn_role = MagicMock()
        rn_role.internal_code = "RN"
        staff.roles.all.return_value = [rn_role]

        assert is_admin(staff, ("ADMIN", "OWNER")) is False

    def test_roles_manager_exception_returns_false(self):
        staff = MagicMock()
        staff.top_clinical_role.internal_code = ""
        staff.roles.all.side_effect = RuntimeError("db unavailable")

        assert is_admin(staff, ("ADMIN",)) is False

    def test_missing_top_role_and_roles_manager(self):
        staff = MagicMock()
        staff.top_clinical_role = None
        staff.roles = None

        assert is_admin(staff, ("ADMIN",)) is False
