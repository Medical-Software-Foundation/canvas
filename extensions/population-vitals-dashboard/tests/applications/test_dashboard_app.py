"""Tests for PopulationDashboardApp Application handler."""

from unittest.mock import MagicMock, patch

from population_vitals_dashboard.applications.dashboard_app import (
    _CACHE_BUST,
    PopulationDashboardApp,
)


def test_on_open_returns_launch_modal_page_effect() -> None:
    """on_open() returns a single LaunchModalEffect targeting PAGE."""
    mock_applied_effect = MagicMock()

    with patch(
        "population_vitals_dashboard.applications.dashboard_app.LaunchModalEffect"
    ) as mock_launch_modal:
        mock_launch_modal.TargetType = MagicMock()
        mock_launch_modal.TargetType.PAGE = "PAGE"
        mock_launch_modal.return_value.apply.return_value = mock_applied_effect

        app = PopulationDashboardApp(event=MagicMock(), secrets={})
        result = app.on_open()

    assert mock_launch_modal.call_count == 1
    kwargs = mock_launch_modal.call_args.kwargs
    assert kwargs["target"] == "PAGE"
    # URL must point at the /app/ endpoint with cache-bust token.
    assert "/plugin-io/api/population_vitals_dashboard/app/" in kwargs["url"]
    assert f"v={_CACHE_BUST}" in kwargs["url"]
    mock_launch_modal.return_value.apply.assert_called_once()
    assert result is mock_applied_effect


def test_on_open_url_contains_correct_prefix() -> None:
    """The LaunchModalEffect URL uses the plugin's registered API prefix."""
    with patch(
        "population_vitals_dashboard.applications.dashboard_app.LaunchModalEffect"
    ) as mock_launch_modal:
        mock_launch_modal.TargetType = MagicMock()
        mock_launch_modal.TargetType.PAGE = "PAGE"
        mock_launch_modal.return_value.apply.return_value = MagicMock()

        app = PopulationDashboardApp(event=MagicMock(), secrets={})
        app.on_open()

    url = mock_launch_modal.call_args.kwargs["url"]
    assert url.startswith("/plugin-io/api/population_vitals_dashboard/app/")
