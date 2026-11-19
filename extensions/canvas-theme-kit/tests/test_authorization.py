"""Tests for the StaffRole-based authorization gate.

The behavior that matters most here is deny-by-default: an install where the
config variables were never set must authorize nobody, rather than falling open
to "any staff member" and letting anyone restyle every patient-facing page.
"""

from unittest.mock import MagicMock, call, patch

import pytest

from canvas_theme_kit.authorization import (
    EDITOR_ROLES_KEY,
    PUBLISHER_ROLES_KEY,
    can_edit,
    can_publish,
    current_staff,
    parse_role_codes,
    staff_role_codes,
)


def make_staff(*codes: str) -> MagicMock:
    """A Staff double whose `roles` manager yields roles with these codes."""
    staff = MagicMock()
    staff.roles.all.return_value = [
        MagicMock(internal_code=code) for code in codes
    ]
    return staff


class TestParseRoleCodes:
    def test_splits_and_strips(self) -> None:
        assert parse_role_codes(" admin , designer ") == {"admin", "designer"}

    @pytest.mark.parametrize("raw", ["", None, "   ", ",,,"])
    def test_empty_inputs_yield_empty_set(self, raw: object) -> None:
        assert parse_role_codes(raw) == set()

    def test_single_code(self) -> None:
        assert parse_role_codes("admin") == {"admin"}


class TestStaffRoleCodes:
    def test_collects_internal_codes(self) -> None:
        staff = make_staff("admin", "designer")
        assert staff_role_codes(staff) == {"admin", "designer"}
        assert staff.roles.all.mock_calls == [call()]

    def test_skips_roles_without_a_code(self) -> None:
        staff = MagicMock()
        staff.roles.all.return_value = [
            MagicMock(internal_code="admin"),
            MagicMock(internal_code=None),
            MagicMock(internal_code=""),
        ]
        assert staff_role_codes(staff) == {"admin"}


class TestCanEdit:
    def test_denies_when_unconfigured(self) -> None:
        # The load-bearing default. An install that never set the allowlist
        # authorizes nobody, including staff who hold every role.
        assert can_edit(make_staff("admin"), {}) is False

    def test_denies_when_config_is_empty_string(self) -> None:
        assert can_edit(make_staff("admin"), {EDITOR_ROLES_KEY: ""}) is False

    def test_denies_anonymous(self) -> None:
        assert can_edit(None, {EDITOR_ROLES_KEY: "admin"}) is False

    def test_allows_matching_role(self) -> None:
        assert can_edit(make_staff("admin"), {EDITOR_ROLES_KEY: "admin"}) is True

    def test_allows_when_any_role_matches(self) -> None:
        secrets = {EDITOR_ROLES_KEY: "designer,admin"}
        assert can_edit(make_staff("nurse", "admin"), secrets) is True

    def test_denies_non_matching_role(self) -> None:
        assert can_edit(make_staff("nurse"), {EDITOR_ROLES_KEY: "admin"}) is False

    def test_matches_on_code_not_name(self) -> None:
        # Role display names can be renamed or localized by an organization.
        # Matching on them would let a rename silently grant or revoke access.
        staff = MagicMock()
        staff.roles.all.return_value = [
            MagicMock(internal_code="role-7", name="Administrator")
        ]
        assert can_edit(staff, {EDITOR_ROLES_KEY: "Administrator"}) is False
        assert can_edit(staff, {EDITOR_ROLES_KEY: "role-7"}) is True

    def test_handles_none_secrets(self) -> None:
        assert can_edit(make_staff("admin"), None) is False


class TestCanPublish:
    def test_denies_when_unconfigured(self) -> None:
        assert can_publish(make_staff("admin"), {}) is False

    def test_denies_anonymous(self) -> None:
        assert can_publish(None, {PUBLISHER_ROLES_KEY: "admin"}) is False

    def test_allows_matching_publisher_role(self) -> None:
        secrets = {PUBLISHER_ROLES_KEY: "release-manager"}
        assert can_publish(make_staff("release-manager"), secrets) is True

    def test_falls_back_to_editor_list_when_publisher_unset(self) -> None:
        secrets = {EDITOR_ROLES_KEY: "designer"}
        assert can_publish(make_staff("designer"), secrets) is True

    def test_fallback_is_never_wider_than_editor_list(self) -> None:
        secrets = {EDITOR_ROLES_KEY: "designer"}
        assert can_publish(make_staff("nurse"), secrets) is False

    def test_publisher_list_does_not_inherit_editors(self) -> None:
        # An editor who is not a publisher can draft but must not ship. This is
        # the whole point of splitting the two permissions.
        secrets = {
            EDITOR_ROLES_KEY: "designer",
            PUBLISHER_ROLES_KEY: "release-manager",
        }
        designer = make_staff("designer")
        assert can_edit(designer, secrets) is True
        assert can_publish(designer, secrets) is False


class TestCurrentStaff:
    def test_resolves_staff_from_header(self) -> None:
        sentinel = MagicMock()
        with patch("canvas_theme_kit.authorization.Staff") as mock_staff:
            mock_staff.objects.get.return_value = sentinel
            result = current_staff({"canvas-logged-in-user-id": "staff-123"})

            assert result is sentinel
            assert mock_staff.objects.mock_calls == [call.get(id="staff-123")]

    def test_returns_none_when_header_missing(self) -> None:
        with patch("canvas_theme_kit.authorization.Staff") as mock_staff:
            assert current_staff({}) is None
            assert mock_staff.objects.mock_calls == []

    def test_returns_none_when_header_empty(self) -> None:
        with patch("canvas_theme_kit.authorization.Staff") as mock_staff:
            assert current_staff({"canvas-logged-in-user-id": ""}) is None
            assert mock_staff.objects.mock_calls == []

    def test_returns_none_for_a_patient_session(self) -> None:
        # A patient-portal session carries the same header. Resolving it against
        # Staff must miss rather than be assumed to be staff.
        class DoesNotExist(Exception):
            pass

        with patch("canvas_theme_kit.authorization.Staff") as mock_staff:
            mock_staff.DoesNotExist = DoesNotExist
            mock_staff.objects.get.side_effect = DoesNotExist()

            assert current_staff({"canvas-logged-in-user-id": "patient-9"}) is None
            assert mock_staff.objects.mock_calls == [call.get(id="patient-9")]

    def test_returns_none_when_headers_are_not_subscriptable(self) -> None:
        with patch("canvas_theme_kit.authorization.Staff") as mock_staff:
            assert current_staff(None) is None
            assert mock_staff.objects.mock_calls == []
