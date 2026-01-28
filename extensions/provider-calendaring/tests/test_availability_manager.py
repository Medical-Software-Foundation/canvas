"""Comprehensive tests for provider_scheduling availability_manager."""

from unittest.mock import Mock, patch

from provider_scheduling.applications.availability_manager import AvailabilityManager


class DummyEvent:
    """A dummy event object for testing Application handlers."""

    def __init__(self, context: dict[str, object] | None = None) -> None:
        self.context = context or {}


def test_application_on_open_returns_launch_modal_effect() -> None:
    """Test on_open method returns LaunchModalEffect."""
    # Create application instance
    dummy_context = {"event_type": "on_open"}
    app = AvailabilityManager(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]

    # Mock LaunchModalEffect
    mock_effect = Mock()
    mock_effect.apply.return_value = mock_effect

    with patch(
        "provider_scheduling.applications.availability_manager.LaunchModalEffect"
    ) as mock_launch_modal:
        mock_launch_modal.return_value = mock_effect

        result = app.on_open()

        # Verify LaunchModalEffect was called with correct parameters
        mock_launch_modal.assert_called_once_with(
            url="/plugin-io/api/provider_scheduling/app/availability-app",
            target=mock_launch_modal.TargetType.PAGE,
        )

        # Verify apply was called
        mock_effect.apply.assert_called_once()

        # Verify result is the effect
        assert result == mock_effect


def test_application_on_open_uses_correct_url() -> None:
    """Test on_open method uses correct plugin URL."""
    # Create application instance
    dummy_context = {"event_type": "on_open"}
    app = AvailabilityManager(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]

    # Mock LaunchModalEffect
    mock_effect = Mock()
    mock_effect.apply.return_value = mock_effect

    with patch(
        "provider_scheduling.applications.availability_manager.LaunchModalEffect"
    ) as mock_launch_modal:
        mock_launch_modal.return_value = mock_effect

        app.on_open()

        # Verify URL points to correct availability manager endpoint
        call_args = mock_launch_modal.call_args
        assert call_args[1]["url"] == "/plugin-io/api/provider_scheduling/app/availability-app"


def test_application_on_open_uses_default_modal_target() -> None:
    """Test on_open method uses PAGE target type."""
    # Create application instance
    dummy_context = {"event_type": "on_open"}
    app = AvailabilityManager(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]

    # Mock LaunchModalEffect
    mock_effect = Mock()
    mock_effect.apply.return_value = mock_effect

    with patch(
        "provider_scheduling.applications.availability_manager.LaunchModalEffect"
    ) as mock_launch_modal:
        mock_launch_modal.return_value = mock_effect

        app.on_open()

        # Verify target is PAGE
        call_args = mock_launch_modal.call_args
        assert call_args[1]["target"] == mock_launch_modal.TargetType.PAGE
