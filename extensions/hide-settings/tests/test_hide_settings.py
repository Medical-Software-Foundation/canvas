"""Tests for the HideSettingsForUnlistedRoles handler."""

import json
from collections.abc import Iterator
from unittest.mock import MagicMock, Mock, patch

import pytest
from canvas_sdk.effects import EffectType
from canvas_sdk.effects.provider_menu_configuration import ProviderMenuConfiguration
from canvas_sdk.v1.data.staff import Staff

from hide_settings.handlers.hide_settings import (
    ITEMS_WITHOUT_SETTINGS,
    HideSettingsForUnlistedRoles,
)

STAFF_ID = "4150cd20de8a470aa570a852859ac87e"
MODULE = "hide_settings.handlers.hide_settings"


def make_handler(user: object) -> HideSettingsForUnlistedRoles:
    """Build a handler whose event context carries the given user."""
    event = Mock()
    event.context = {} if user is None else {"user": user}
    return HideSettingsForUnlistedRoles(event=event)


def staff_with_roles(*codes: str) -> MagicMock:
    """A Staff stand-in whose roles return the given internal codes."""
    staff = MagicMock()
    staff.roles.values_list.return_value = list(codes)
    return staff


@pytest.fixture
def config() -> Iterator[MagicMock]:
    """Patch the stored configuration; tests set allowed_role_codes on the returned mock."""
    with patch(f"{MODULE}.SettingsAccessConfig") as model:
        stored = MagicMock()
        model.objects.first.return_value = stored
        yield stored


@pytest.fixture
def staff_get() -> Iterator[MagicMock]:
    """Patch Staff.objects.get, keeping the real DoesNotExist."""
    with patch(f"{MODULE}.Staff") as model:
        model.DoesNotExist = Staff.DoesNotExist
        yield model.objects.get


def menu_items(effects: list) -> list[str]:
    """Return the menu items from a single provider menu effect."""
    assert len(effects) == 1
    assert effects[0].type == EffectType.SHOW_PROVIDER_MENU_ITEMS
    return list(json.loads(effects[0].payload)["data"]["items"])


def test_items_without_settings_is_every_other_item() -> None:
    """The hidden-menu list drops Settings and keeps every other SDK menu item."""
    items = ProviderMenuConfiguration.Items
    assert items.SETTINGS not in ITEMS_WITHOUT_SETTINGS
    assert set(ITEMS_WITHOUT_SETTINGS) == set(items) - {items.SETTINGS}


def test_no_configuration_leaves_menu_alone(staff_get: MagicMock) -> None:
    """Before an admin saves anything, no effect is returned."""
    with patch(f"{MODULE}.SettingsAccessConfig") as model:
        model.objects.first.return_value = None
        effects = make_handler({"type": "Staff", "id": STAFF_ID}).compute()

    assert effects == []
    staff_get.assert_not_called()


def test_empty_allowed_list_leaves_menu_alone(config: MagicMock, staff_get: MagicMock) -> None:
    """A saved configuration with no roles checked does not hide Settings from anyone."""
    config.allowed_role_codes = []

    assert make_handler({"type": "Staff", "id": STAFF_ID}).compute() == []
    staff_get.assert_not_called()


def test_null_allowed_list_leaves_menu_alone(config: MagicMock, staff_get: MagicMock) -> None:
    """A null stored list behaves like an empty one."""
    config.allowed_role_codes = None

    assert make_handler({"type": "Staff", "id": STAFF_ID}).compute() == []


def test_staff_with_allowed_role_keeps_settings(config: MagicMock, staff_get: MagicMock) -> None:
    """A staff member holding an allowed role gets no override."""
    config.allowed_role_codes = ["AD", "MD"]
    staff_get.return_value = staff_with_roles("MD")

    assert make_handler({"type": "Staff", "id": STAFF_ID}).compute() == []
    staff_get.assert_called_once_with(id=STAFF_ID)


def test_any_allowed_role_is_enough(config: MagicMock, staff_get: MagicMock) -> None:
    """Holding one allowed role among several unallowed ones keeps Settings."""
    config.allowed_role_codes = ["AD"]
    staff_get.return_value = staff_with_roles("RN", "AD", "CL")

    assert make_handler({"type": "Staff", "id": STAFF_ID}).compute() == []


def test_staff_without_allowed_role_loses_settings(config: MagicMock, staff_get: MagicMock) -> None:
    """A staff member with only unallowed roles gets a menu without Settings."""
    config.allowed_role_codes = ["AD"]
    staff_get.return_value = staff_with_roles("NETPHARM")

    items = menu_items(make_handler({"type": "Staff", "id": STAFF_ID}).compute())

    assert "settings" not in items
    assert "schedule" in items
    assert "patients" in items


def test_staff_with_no_roles_loses_settings(config: MagicMock, staff_get: MagicMock) -> None:
    """A staff member with no roles at all is not on the allowed list."""
    config.allowed_role_codes = ["AD"]
    staff_get.return_value = staff_with_roles()

    assert "settings" not in menu_items(make_handler({"type": "Staff", "id": STAFF_ID}).compute())


@pytest.mark.parametrize(
    "user",
    [
        None,
        {},
        {"type": "Patient", "id": STAFF_ID},
        {"type": "Staff"},
        {"type": "Staff", "id": ""},
    ],
)
def test_missing_or_non_staff_user_is_ignored(
    config: MagicMock, staff_get: MagicMock, user: object
) -> None:
    """Events without a staff user in context return no effect."""
    config.allowed_role_codes = ["AD"]

    assert make_handler(user).compute() == []
    staff_get.assert_not_called()


def test_unknown_staff_is_ignored(config: MagicMock, staff_get: MagicMock) -> None:
    """A staff id with no matching record returns no effect instead of raising."""
    config.allowed_role_codes = ["AD"]
    staff_get.side_effect = Staff.DoesNotExist

    assert make_handler({"type": "Staff", "id": STAFF_ID}).compute() == []
