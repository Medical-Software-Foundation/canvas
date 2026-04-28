"""Tests for the NoteProductionDashboardApp Application handler."""
from unittest.mock import MagicMock, patch

import pytest

from note_production_dashboard.applications.dashboard_app import (
    NoteProductionDashboardApp,
    _CACHE_BUST,
)


def test_on_open_returns_launch_modal_page_effect() -> None:
    """on_open() should return a LaunchModalEffect targeting PAGE with the dashboard URL."""
    mock_effect = MagicMock()

    with patch(
        "note_production_dashboard.applications.dashboard_app.LaunchModalEffect"
    ) as mock_launch_modal:
        mock_launch_modal.TargetType = MagicMock()
        mock_launch_modal.TargetType.PAGE = "PAGE"
        mock_launch_modal.return_value.apply.return_value = mock_effect

        app = NoteProductionDashboardApp(event=MagicMock(), secrets={})
        result = app.on_open()

        # LaunchModalEffect must be invoked with PAGE target, the dashboard URL,
        # and the cache-bust query param so deploys invalidate browser-cached HTML.
        assert mock_launch_modal.call_count == 1
        kwargs = mock_launch_modal.call_args.kwargs
        assert kwargs["target"] == "PAGE"
        assert kwargs["url"] == (
            f"/plugin-io/api/note_production_dashboard/dashboard?v={_CACHE_BUST}"
        )
        mock_launch_modal.return_value.apply.assert_called_once_with()

        assert result is mock_effect
