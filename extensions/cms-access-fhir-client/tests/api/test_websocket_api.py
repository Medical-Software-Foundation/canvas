"""Tests for AccessChartSummaryWebSocket authentication."""
import pytest
from unittest.mock import MagicMock, call


def _make_handler(user=None, channel="access-cms_access_fhir_client-patient-123"):
    from cms_access_fhir_client.api.websocket_api import AccessChartSummaryWebSocket
    handler = AccessChartSummaryWebSocket.__new__(AccessChartSummaryWebSocket)
    ws = MagicMock()
    ws.logged_in_user = user
    ws.channel = channel
    handler.websocket = ws
    return handler, ws


class TestAccessChartSummaryWebSocket:
    def test_staff_user_with_valid_channel_is_authenticated(self):
        handler, ws = _make_handler(user={"id": "staff-abc", "type": "Staff"})
        result = handler.authenticate()

        assert result is True

    def test_no_logged_in_user_rejected(self):
        handler, ws = _make_handler(user=None)
        ws.logged_in_user = None

        result = handler.authenticate()

        assert result is False

    def test_patient_user_rejected(self):
        handler, ws = _make_handler(user={"id": "pat-123", "type": "Patient"})
        result = handler.authenticate()

        assert result is False

    def test_wrong_channel_prefix_rejected(self):
        handler, ws = _make_handler(
            user={"id": "staff-abc", "type": "Staff"},
            channel="some-other-channel-patient-123",
        )
        result = handler.authenticate()

        assert result is False

    def test_correct_channel_prefix_accepted(self):
        handler, ws = _make_handler(
            user={"id": "staff-abc", "type": "Staff"},
            channel="access-cms_access_fhir_client-patient-xyz",
        )
        result = handler.authenticate()
        assert result is True

    def test_channel_must_include_patient_id(self):
        """Channel format enforces patient-scoping at broadcast time."""
        # Verify the prefix constant used in the authenticator matches
        # what the broadcaster produces
        from cms_access_fhir_client.handlers.realtime_broadcaster import broadcast_alignment_update
        import json

        effect = broadcast_alignment_update("abc-patient")
        payload = json.loads(effect.payload)
        channel = payload["data"]["channel"]

        # The channel should pass the WebSocket auth check when used by a staff user
        handler, ws = _make_handler(
            user={"id": "staff-abc", "type": "Staff"},
            channel=channel,
        )
        assert handler.authenticate() is True
