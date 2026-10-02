"""Tests for provider_availability.applications.availability_app."""

import json
from unittest.mock import MagicMock

from provider_availability.applications.availability_app import ProviderAvailabilityApp


class TestProviderAvailabilityApp:
    def test_on_open_returns_launch_modal_effect(self):
        app = ProviderAvailabilityApp(MagicMock())

        result = app.on_open()

        assert result.__class__.__name__ == "Effect"

    def test_on_open_modal_targets_new_window(self):
        """The admin UI opens in a new browser tab (NEW_WINDOW), not in-place."""
        app = ProviderAvailabilityApp(MagicMock())

        result = app.on_open()

        payload = json.loads(result.payload)
        assert payload["data"]["target"] == "new_window"
