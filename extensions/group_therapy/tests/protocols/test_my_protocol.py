"""Tests for group_therapy.protocols.my_protocol."""

from unittest.mock import MagicMock, call, patch

from group_therapy.protocols.my_protocol import (
    GroupTherapyAdminApplication,
    GroupTherapyApplication,
)


class TestGroupTherapyApplication:
    def test_on_open_returns_launch_modal_effect(self):
        handler = GroupTherapyApplication()
        handler.event = MagicMock()

        with patch(
            "group_therapy.protocols.my_protocol.LaunchModalEffect"
        ) as mock_modal:
            mock_effect = MagicMock()
            mock_modal.return_value.apply.return_value = mock_effect

            result = handler.on_open()

            kwargs = mock_modal.call_args.kwargs
            # URL carries a cache-bust param so updates aren't served from a stale iframe cache
            assert kwargs["url"].startswith("/plugin-io/api/group_therapy/ui?v=")
            assert kwargs["target"] == mock_modal.TargetType.PAGE
            assert result == mock_effect


class TestGroupTherapyAdminApplication:
    def test_on_open_launches_admin_page(self):
        handler = GroupTherapyAdminApplication()
        handler.event = MagicMock()
        with patch("group_therapy.protocols.my_protocol.LaunchModalEffect") as mock_modal:
            mock_modal.return_value.apply.return_value = "ADMIN_EFFECT"
            result = handler.on_open()
            kwargs = mock_modal.call_args.kwargs
            assert kwargs["url"].startswith("/plugin-io/api/group_therapy/admin/ui?v=")
            assert kwargs["target"] == mock_modal.TargetType.PAGE
            assert result == "ADMIN_EFFECT"
