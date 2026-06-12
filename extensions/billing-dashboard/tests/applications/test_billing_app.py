"""Tests for BillingDashboard Application handler."""

import pytest
from unittest.mock import MagicMock, call, patch

from billing_dashboard.applications.billing_app import BillingDashboard


class TestBillingDashboardApplication:
    """Tests for the BillingDashboard Application on_open method."""

    def test_on_open_returns_launch_modal_effect(self, mock_event: MagicMock) -> None:
        """Test that on_open returns a LaunchModalEffect targeting PAGE."""
        handler = BillingDashboard(event=mock_event)

        with patch(
            "billing_dashboard.applications.billing_app.LaunchModalEffect"
        ) as mock_launch_modal:
            mock_effect = MagicMock()
            mock_launch_modal.return_value.apply.return_value = mock_effect

            result = handler.on_open()

            # Verify LaunchModalEffect was constructed with correct args
            assert mock_launch_modal.mock_calls == [
                call(
                    url="/plugin-io/api/billing_dashboard/dashboard",
                    target=mock_launch_modal.TargetType.PAGE,
                    title="Billing Dashboard",
                ),
                call().apply(),
            ]

            # Verify mock_event not accessed during on_open
            assert mock_event.mock_calls == []

            # Verify result is the effect returned by apply()
            assert result == mock_effect

    def test_on_open_uses_page_target(self, mock_event: MagicMock) -> None:
        """Test that the modal target is PAGE (full-page modal)."""
        handler = BillingDashboard(event=mock_event)

        with patch(
            "billing_dashboard.applications.billing_app.LaunchModalEffect"
        ) as mock_launch_modal:
            mock_launch_modal.return_value.apply.return_value = MagicMock()

            handler.on_open()

            # Extract the target argument from the constructor call
            kwargs = mock_launch_modal.call_args.kwargs
            assert kwargs["target"] == mock_launch_modal.TargetType.PAGE

            assert mock_event.mock_calls == []

    def test_on_open_uses_correct_url(self, mock_event: MagicMock) -> None:
        """Test that the modal URL points to the billing dashboard API endpoint."""
        handler = BillingDashboard(event=mock_event)

        with patch(
            "billing_dashboard.applications.billing_app.LaunchModalEffect"
        ) as mock_launch_modal:
            mock_launch_modal.return_value.apply.return_value = MagicMock()

            handler.on_open()

            kwargs = mock_launch_modal.call_args.kwargs
            assert kwargs["url"] == "/plugin-io/api/billing_dashboard/dashboard"

            assert mock_event.mock_calls == []

    def test_on_open_uses_correct_title(self, mock_event: MagicMock) -> None:
        """Test that the modal title is 'Billing Dashboard'."""
        handler = BillingDashboard(event=mock_event)

        with patch(
            "billing_dashboard.applications.billing_app.LaunchModalEffect"
        ) as mock_launch_modal:
            mock_launch_modal.return_value.apply.return_value = MagicMock()

            handler.on_open()

            kwargs = mock_launch_modal.call_args.kwargs
            assert kwargs["title"] == "Billing Dashboard"

            assert mock_event.mock_calls == []
