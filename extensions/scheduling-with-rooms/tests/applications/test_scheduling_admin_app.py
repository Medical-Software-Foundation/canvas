"""Tests for scheduling_admin_app.py."""

from unittest.mock import MagicMock, patch

from scheduling_with_rooms.applications.scheduling_admin_app import (
    SchedulingAdminApp,
)


def test_on_open_returns_admin_page_modal():
    handler = SchedulingAdminApp.__new__(SchedulingAdminApp)

    fake_effect = MagicMock(name="fake_effect")
    with patch(
        "scheduling_with_rooms.applications.scheduling_admin_app.LaunchModalEffect"
    ) as mock_modal:
        mock_modal.TargetType.PAGE = "PAGE"
        mock_modal.return_value.apply.return_value = fake_effect

        result = handler.on_open()

        ctor_call, apply_call = mock_modal.mock_calls[0], mock_modal.mock_calls[1]
        kwargs = ctor_call.kwargs
        assert kwargs["url"].startswith("/plugin-io/api/scheduling_with_rooms/admin?v=")
        assert kwargs["target"] == "PAGE"
        assert kwargs["title"] == "Scheduling Admin"
        assert apply_call[0] == "().apply"
        assert result is fake_effect
