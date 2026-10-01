"""Tests for candid.access dashboard authorization helpers."""

from unittest.mock import MagicMock, patch

from candid.access import (
    ALLOWED_ROLES_SECRET,
    ALLOWED_STAFF_KEYS_SECRET,
    staff_can_access_dashboard,
)


def _role(internal_code="", public_abbreviation="", name=""):
    role = MagicMock()
    role.internal_code = internal_code
    role.public_abbreviation = public_abbreviation
    role.name = name
    return role


def _staff_with_roles(*roles):
    staff = MagicMock()
    staff.roles.all.return_value = list(roles)
    return staff


def test_unconfigured_allows_everyone():
    assert staff_can_access_dashboard("staff-1", {}) is True
    assert staff_can_access_dashboard(None, {}) is True


def test_whitespace_only_secret_treated_as_unset():
    # A secret that is only commas/spaces leaves access open to everyone.
    assert staff_can_access_dashboard("anyone", {ALLOWED_STAFF_KEYS_SECRET: " , "}) is True


def test_staff_key_allowlist():
    secrets = {ALLOWED_STAFF_KEYS_SECRET: "staff-1, staff-2"}
    assert staff_can_access_dashboard("staff-2", secrets) is True
    assert staff_can_access_dashboard("staff-3", secrets) is False


def test_missing_staff_key_denied_when_restricted():
    assert staff_can_access_dashboard(None, {ALLOWED_STAFF_KEYS_SECRET: "staff-1"}) is False


def test_role_allowlist_matches_internal_code():
    secrets = {ALLOWED_ROLES_SECRET: "BILL"}
    with patch("candid.access.Staff") as MockStaff:
        MockStaff.objects.filter.return_value.first.return_value = _staff_with_roles(
            _role(internal_code="BILL", name="Biller")
        )
        assert staff_can_access_dashboard("staff-1", secrets) is True


def test_role_allowlist_matches_name_case_insensitively():
    secrets = {ALLOWED_ROLES_SECRET: "biller"}
    with patch("candid.access.Staff") as MockStaff:
        MockStaff.objects.filter.return_value.first.return_value = _staff_with_roles(
            _role(internal_code="BILL", name="Biller")
        )
        assert staff_can_access_dashboard("staff-1", secrets) is True


def test_role_allowlist_matches_public_abbreviation():
    secrets = {ALLOWED_ROLES_SECRET: "MD"}
    with patch("candid.access.Staff") as MockStaff:
        MockStaff.objects.filter.return_value.first.return_value = _staff_with_roles(
            _role(internal_code="PHYS", public_abbreviation="MD", name="Physician")
        )
        assert staff_can_access_dashboard("staff-1", secrets) is True


def test_role_allowlist_denies_non_matching_role():
    secrets = {ALLOWED_ROLES_SECRET: "BILL"}
    with patch("candid.access.Staff") as MockStaff:
        MockStaff.objects.filter.return_value.first.return_value = _staff_with_roles(
            _role(internal_code="MA", name="Medical Assistant")
        )
        assert staff_can_access_dashboard("staff-1", secrets) is False


def test_role_allowlist_denies_unknown_staff():
    secrets = {ALLOWED_ROLES_SECRET: "BILL"}
    with patch("candid.access.Staff") as MockStaff:
        MockStaff.objects.filter.return_value.first.return_value = None
        assert staff_can_access_dashboard("staff-x", secrets) is False


def test_staff_key_match_short_circuits_role_lookup():
    secrets = {ALLOWED_STAFF_KEYS_SECRET: "staff-1", ALLOWED_ROLES_SECRET: "BILL"}
    with patch("candid.access.Staff") as MockStaff:
        assert staff_can_access_dashboard("staff-1", secrets) is True
        MockStaff.objects.filter.assert_not_called()
