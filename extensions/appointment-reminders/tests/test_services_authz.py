"""Tests for the admin role gate.

The behavior that matters most here is what happens when the secret is missing
or the staff member is unknown: both must deny.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

from appointment_reminders.services.authz import admin_role_names, is_admin_staff

_MOD = "appointment_reminders.services.authz"


@contextmanager
def _roles(rows: list[tuple[str, str]]):
    """Patch StaffRole so the role query yields ``rows`` of (name, internal_code)."""
    with patch(f"{_MOD}.StaffRole") as mock_role:
        mock_role.objects.filter.return_value.values_list.return_value = rows
        yield mock_role


def test_admin_role_names_parses_and_casefolds() -> None:
    assert admin_role_names({"ADMIN_ROLE_NAMES": " Practice Manager , ADMIN "}) == {
        "practice manager",
        "admin",
    }


def test_admin_role_names_empty_when_unset() -> None:
    assert admin_role_names({}) == set()
    assert admin_role_names({"ADMIN_ROLE_NAMES": "  ,  "}) == set()


def test_denies_everyone_when_secret_is_unset() -> None:
    """Fail closed: a missing secret must not open the console to all staff."""
    with _roles([("Practice Manager", "PM")]) as mock_role:
        assert is_admin_staff("s1", {}) is False
    mock_role.objects.filter.assert_not_called()  # denied before any query


def test_denies_when_secret_is_blank() -> None:
    with _roles([("Practice Manager", "PM")]):
        assert is_admin_staff("s1", {"ADMIN_ROLE_NAMES": "   "}) is False


def test_denies_when_staff_id_missing() -> None:
    with _roles([("Practice Manager", "PM")]):
        assert is_admin_staff(None, {"ADMIN_ROLE_NAMES": "Admin"}) is False
        assert is_admin_staff("", {"ADMIN_ROLE_NAMES": "Admin"}) is False


def test_allows_staff_holding_a_configured_role_name() -> None:
    with _roles([("Registered Nurse", "RN"), ("Practice Manager", "PM")]):
        assert is_admin_staff("s1", {"ADMIN_ROLE_NAMES": "Practice Manager"}) is True


def test_role_matching_is_case_insensitive() -> None:
    with _roles([("practice MANAGER", "PM")]):
        assert is_admin_staff("s1", {"ADMIN_ROLE_NAMES": "Practice Manager"}) is True


def test_allows_matching_on_internal_code() -> None:
    """Either the display name or the internal code may be listed."""
    with _roles([("Practice Manager", "PM")]):
        assert is_admin_staff("s1", {"ADMIN_ROLE_NAMES": "PM"}) is True


def test_denies_staff_holding_only_other_roles() -> None:
    with _roles([("Registered Nurse", "RN"), ("Front Desk", "FD")]):
        assert is_admin_staff("s1", {"ADMIN_ROLE_NAMES": "Practice Manager"}) is False


def test_denies_staff_with_no_roles_at_all() -> None:
    with _roles([]):
        assert is_admin_staff("s1", {"ADMIN_ROLE_NAMES": "Practice Manager"}) is False


def test_queries_only_the_requested_staff_member() -> None:
    with _roles([("Practice Manager", "PM")]) as mock_role:
        is_admin_staff("staff-9", {"ADMIN_ROLE_NAMES": "Practice Manager"})
    mock_role.objects.filter.assert_called_once_with(staff__id="staff-9")
