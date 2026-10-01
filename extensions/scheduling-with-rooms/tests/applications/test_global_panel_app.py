"""Tests for global_panel_app.py."""

from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

from scheduling_with_rooms.applications.global_panel_app import (
    GlobalPanelSchedulingWithRoomsApp,
)


def test_on_open_launches_an_empty_modal_tagged_with_our_origin():
    handler = GlobalPanelSchedulingWithRoomsApp.__new__(GlobalPanelSchedulingWithRoomsApp)

    fake_effect = MagicMock(name="fake_effect")
    with patch(
        "scheduling_with_rooms.applications.global_panel_app.LaunchModalEffect"
    ) as mock_modal:
        mock_modal.TargetType.DEFAULT_MODAL = "DEFAULT_MODAL"
        mock_modal.return_value.apply.return_value = fake_effect

        result = handler.on_open()

    kwargs = mock_modal.call_args.kwargs
    parsed = urlparse(kwargs["url"])
    params = parse_qs(parsed.query)
    assert parsed.path == "/plugin-io/api/scheduling_with_rooms/modal"
    # No entity context — just the cache-bust and the origin marker the modal
    # uses to decide it should close itself after a successful booking.
    assert set(params) == {"v", "origin"}
    assert params["origin"] == ["global_panel"]
    assert kwargs["target"] == "DEFAULT_MODAL"
    assert kwargs["title"] == "Schedule Appointment"
    assert result is fake_effect


def test_on_open_does_not_read_event_context():
    """The panel button is context-free, so it must not require an event."""
    handler = GlobalPanelSchedulingWithRoomsApp.__new__(GlobalPanelSchedulingWithRoomsApp)

    with patch(
        "scheduling_with_rooms.applications.global_panel_app.LaunchModalEffect"
    ) as mock_modal:
        mock_modal.TargetType.DEFAULT_MODAL = "DEFAULT_MODAL"
        handler.on_open()

    assert not hasattr(handler, "event")
