"""Tests for scheduling_with_rooms_app.py."""

from unittest.mock import MagicMock, patch

from scheduling_with_rooms.applications.scheduling_with_rooms_app import (
    SchedulingWithRoomsApp,
)


def test_on_open_returns_launch_modal_effect():
    handler = SchedulingWithRoomsApp.__new__(SchedulingWithRoomsApp)

    fake_effect = MagicMock(name="fake_effect")
    with patch(
        "scheduling_with_rooms.applications.scheduling_with_rooms_app.LaunchModalEffect"
    ) as mock_modal:
        mock_modal.TargetType.DEFAULT_MODAL = "DEFAULT_MODAL"
        mock_modal.return_value.apply.return_value = fake_effect

        result = handler.on_open()

        # Two calls: the constructor and the .apply() chain.
        ctor_call, apply_call = mock_modal.mock_calls[0], mock_modal.mock_calls[1]
        kwargs = ctor_call.kwargs
        assert kwargs["url"].startswith("/plugin-io/api/scheduling_with_rooms/modal?v=")
        assert kwargs["target"] == "DEFAULT_MODAL"
        assert kwargs["title"] == "Schedule Appointment"
        assert apply_call[0] == "().apply"
        assert result is fake_effect
