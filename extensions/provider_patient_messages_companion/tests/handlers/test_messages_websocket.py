"""Tests for provider_patient_messages_companion.handlers.messages_websocket."""
from types import SimpleNamespace

from provider_patient_messages_companion.handlers.messages_websocket import (
    PatientMessagesWebSocket,
)

STAFF_UUID = "00000000-0000-0000-0000-000000000001"


def _make_handler(channel: str, logged_in_user: dict | None) -> PatientMessagesWebSocket:
    handler = PatientMessagesWebSocket.__new__(PatientMessagesWebSocket)
    # cached_property with a pre-built WebSocket-like stub
    handler.__dict__["websocket"] = SimpleNamespace(
        channel=channel, logged_in_user=logged_in_user
    )
    return handler


class TestAuthenticate:
    def test_staff_with_matching_channel_passes(self) -> None:
        handler = _make_handler(f"staff-{STAFF_UUID}", {"id": STAFF_UUID, "type": "Staff"})
        assert handler.authenticate() is True

    def test_staff_with_wrong_channel_rejected(self) -> None:
        handler = _make_handler("staff-someone-else", {"id": STAFF_UUID, "type": "Staff"})
        assert handler.authenticate() is False

    def test_patient_session_rejected(self) -> None:
        handler = _make_handler(f"staff-{STAFF_UUID}", {"id": STAFF_UUID, "type": "Patient"})
        assert handler.authenticate() is False

    def test_no_session_rejected(self) -> None:
        handler = _make_handler(f"staff-{STAFF_UUID}", None)
        assert handler.authenticate() is False
