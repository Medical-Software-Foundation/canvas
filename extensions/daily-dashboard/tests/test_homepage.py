"""Tests for the homepage-override handler.

The handler answers GET_HOMEPAGE_CONFIGURATION with a DefaultHomepageEffect
pointed at the dashboard Application, replacing the default schedule landing.
``apply()`` validates the application against the live plugin registry (absent
in tests), so the effect class is patched to assert the wiring instead.
"""

from unittest.mock import Mock, patch

from daily_dashboard.handlers import homepage
from daily_dashboard.handlers.homepage import (
    DASHBOARD_APP_IDENTIFIER,
    HomepageHandler,
)


def test_homepage_handler_points_at_dashboard() -> None:
    handler = HomepageHandler(event=Mock())

    with patch.object(homepage, "DefaultHomepageEffect") as effect_cls:
        effect_cls.return_value.apply.return_value = "applied-effect"
        result = handler.compute()

    # Built with the dashboard application identifier, applied, and returned.
    effect_cls.assert_called_once_with(application_identifier=DASHBOARD_APP_IDENTIFIER)
    assert result == ["applied-effect"]


def test_homepage_handler_responds_to_homepage_config() -> None:
    assert HomepageHandler.RESPONDS_TO == "GET_HOMEPAGE_CONFIGURATION"
