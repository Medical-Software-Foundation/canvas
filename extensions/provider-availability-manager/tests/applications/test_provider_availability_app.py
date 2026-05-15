"""Smoke test for the provider-menu Application."""

from unittest.mock import MagicMock, patch

from provider_availability_manager.applications.provider_availability_app import (
    ProviderAvailabilityManagerApp,
)


def test_on_open_returns_page_modal():
    handler = ProviderAvailabilityManagerApp.__new__(ProviderAvailabilityManagerApp)

    fake_effect = MagicMock(name="fake_effect")
    with patch(
        "provider_availability_manager.applications.provider_availability_app.LaunchModalEffect"
    ) as mock_modal:
        mock_modal.TargetType.PAGE = "PAGE"
        mock_modal.return_value.apply.return_value = fake_effect

        result = handler.on_open()

        ctor_call = mock_modal.mock_calls[0]
        kwargs = ctor_call.kwargs
        assert kwargs["url"].startswith(
            "/plugin-io/api/provider_availability_manager/app/availability-app?v="
        )
        assert kwargs["target"] == "PAGE"
        assert kwargs["title"] == "Manage Availability"
        assert result is fake_effect
