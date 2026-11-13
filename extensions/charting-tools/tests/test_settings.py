from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from charting_tools.settings import scribe_enabled, staff_can_manage_templates


@pytest.mark.parametrize(
    ("value", "expected"),
    [("true", True), ("TRUE", True), ("1", True), ("yes", True), ("false", False), ("", False), (None, False)],
)
def test_scribe_enabled(value: str | None, expected: bool) -> None:
    secrets = {} if value is None else {"SCRIBE_ENABLED": value}
    assert scribe_enabled(secrets) is expected


def _patch_staff(mocker: MagicMock, roles: list[SimpleNamespace] | None) -> None:
    staff = None if roles is None else SimpleNamespace(roles=SimpleNamespace(all=lambda: roles))
    query = mocker.patch("charting_tools.settings.Staff.objects.filter")
    query.return_value.prefetch_related.return_value.first.return_value = staff


def _role(code: str = "", abbreviation: str = "", name: str = "") -> SimpleNamespace:
    return SimpleNamespace(internal_code=code, public_abbreviation=abbreviation, name=name)


def test_admin_fails_closed_when_setting_empty(mocker: MagicMock) -> None:
    _patch_staff(mocker, [_role(code="ADMIN")])
    assert staff_can_manage_templates("staff1", {}) is False
    assert staff_can_manage_templates("staff1", {"TEMPLATE_ADMIN_ROLES": " , "}) is False


def test_admin_denied_without_staff_id(mocker: MagicMock) -> None:
    assert staff_can_manage_templates(None, {"TEMPLATE_ADMIN_ROLES": "ADMIN"}) is False


def test_admin_denied_for_unknown_staff(mocker: MagicMock) -> None:
    _patch_staff(mocker, None)
    assert staff_can_manage_templates("staff1", {"TEMPLATE_ADMIN_ROLES": "ADMIN"}) is False


@pytest.mark.parametrize(
    "role",
    [_role(code="ADMIN"), _role(abbreviation="admin"), _role(name="Clinical Admin")],
)
def test_admin_matches_code_abbreviation_or_name(mocker: MagicMock, role: SimpleNamespace) -> None:
    _patch_staff(mocker, [_role(code="MD"), role])
    secrets = {"TEMPLATE_ADMIN_ROLES": "admin, clinical admin"}
    assert staff_can_manage_templates("staff1", secrets) is True


def test_admin_denied_when_no_role_matches(mocker: MagicMock) -> None:
    _patch_staff(mocker, [_role(code="MD", abbreviation="MD", name="Physician")])
    assert staff_can_manage_templates("staff1", {"TEMPLATE_ADMIN_ROLES": "ADMIN"}) is False
