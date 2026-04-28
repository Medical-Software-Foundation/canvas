"""Tests for the NoteProductionDashboardApp Application handler."""
from unittest.mock import MagicMock, call, patch

import pytest

from note_production_dashboard.applications.dashboard_app import (
    NoteProductionDashboardApp,
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

        # Verify LaunchModalEffect was constructed with correct args.
        assert mock_launch_modal.mock_calls == [
            call(
                url="/plugin-io/api/note_production_dashboard/dashboard",
                target="PAGE",
            ),
            call().apply(),
        ]

        # Verify result is the applied effect.
        assert result is mock_effect
