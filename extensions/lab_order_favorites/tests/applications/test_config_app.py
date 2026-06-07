"""Tests for the provider-menu config application handler."""

from unittest.mock import MagicMock

from lab_order_favorites.applications.config_app import CONFIG_PAGE_URL, LabFavoritesConfigApp


def test_on_open_launches_config_page_in_new_window():
    handler = LabFavoritesConfigApp(MagicMock())

    effect = handler.on_open()

    assert effect is not None
    # The menu item opens the served config page in a new tab.
    assert CONFIG_PAGE_URL in effect.payload
    assert "new_window" in effect.payload
