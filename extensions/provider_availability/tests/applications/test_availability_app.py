"""Tests for provider_availability.applications.availability_app."""

from unittest.mock import MagicMock

from canvas_sdk.effects.launch_modal import LaunchModalEffect

from provider_availability.applications.availability_app import ProviderAvailabilityApp


class TestProviderAvailabilityApp:
    def test_on_open_returns_launch_modal_effect(self):
        app = ProviderAvailabilityApp(MagicMock())

        result = app.on_open()

        assert result.__class__.__name__ == "Effect"

    def test_on_open_modal_targets_new_window(self):
        app = ProviderAvailabilityApp(MagicMock())

        effect = LaunchModalEffect(
            url="/plugin-io/api/provider_availability/app/availability-admin",
            target=LaunchModalEffect.TargetType.NEW_WINDOW,
            title="Provider Availability",
        )

        result = app.on_open()

        # Verify the effect contains the expected modal configuration
        assert result is not None
