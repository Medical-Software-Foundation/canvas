"""Tests for provider_patient_messages_companion.handlers.new_message_notifier."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from canvas_sdk.effects import EffectType

from provider_patient_messages_companion.handlers import new_message_notifier
from provider_patient_messages_companion.handlers.new_message_notifier import (
    NewMessageNotifier,
)

STAFF_UUID = "00000000-0000-0000-0000-000000000001"
PATIENT_UUID = "11111111-1111-1111-1111-111111111111"
MESSAGE_UUID = "22222222-2222-2222-2222-222222222222"


def _make_handler(target_id: str) -> NewMessageNotifier:
    handler = NewMessageNotifier.__new__(NewMessageNotifier)
    handler.event = SimpleNamespace(target=SimpleNamespace(id=target_id))
    return handler


def _patched_message_query(message):
    """Return a context manager that makes Message.objects...get return `message`."""
    queryset = MagicMock()
    queryset.select_related.return_value = queryset
    queryset.filter.return_value = queryset
    queryset.first.return_value = message
    mock_model = MagicMock()
    mock_model.objects = queryset
    return patch.object(new_message_notifier, "Message", mock_model)


def _canvas_user(is_staff: bool, subclass_id: str):
    return SimpleNamespace(
        is_staff=is_staff,
        person_subclass=SimpleNamespace(id=subclass_id),
    )


class TestNewMessageNotifier:
    def test_patient_to_staff_broadcasts_to_staff_channel(self) -> None:
        message = SimpleNamespace(
            id=MESSAGE_UUID,
            sender=_canvas_user(is_staff=False, subclass_id=PATIENT_UUID),
            recipient=_canvas_user(is_staff=True, subclass_id=STAFF_UUID),
        )
        handler = _make_handler(MESSAGE_UUID)
        with _patched_message_query(message):
            effects = handler.compute()

        assert len(effects) == 1
        effect = effects[0]
        assert effect.type == EffectType.SIMPLE_API_WEBSOCKET_BROADCAST
        data = json.loads(effect.payload)["data"]
        assert data["channel"] == f"staff-{STAFF_UUID}"
        assert data["message"] == {
            "type": "new_message",
            "patient_id": PATIENT_UUID,
            "message_id": MESSAGE_UUID,
        }

    def test_staff_to_patient_also_broadcasts(self) -> None:
        message = SimpleNamespace(
            id=MESSAGE_UUID,
            sender=_canvas_user(is_staff=True, subclass_id=STAFF_UUID),
            recipient=_canvas_user(is_staff=False, subclass_id=PATIENT_UUID),
        )
        handler = _make_handler(MESSAGE_UUID)
        with _patched_message_query(message):
            effects = handler.compute()

        assert len(effects) == 1
        data = json.loads(effects[0].payload)["data"]
        assert data["channel"] == f"staff-{STAFF_UUID}"

    def test_staff_to_staff_skipped(self) -> None:
        message = SimpleNamespace(
            id=MESSAGE_UUID,
            sender=_canvas_user(is_staff=True, subclass_id=STAFF_UUID),
            recipient=_canvas_user(is_staff=True, subclass_id="other-staff"),
        )
        handler = _make_handler(MESSAGE_UUID)
        with _patched_message_query(message):
            assert handler.compute() == []

    def test_patient_to_patient_skipped(self) -> None:
        message = SimpleNamespace(
            id=MESSAGE_UUID,
            sender=_canvas_user(is_staff=False, subclass_id=PATIENT_UUID),
            recipient=_canvas_user(is_staff=False, subclass_id="other-patient"),
        )
        handler = _make_handler(MESSAGE_UUID)
        with _patched_message_query(message):
            assert handler.compute() == []

    def test_null_sender_skipped(self) -> None:
        message = SimpleNamespace(
            id=MESSAGE_UUID,
            sender=None,
            recipient=_canvas_user(is_staff=True, subclass_id=STAFF_UUID),
        )
        handler = _make_handler(MESSAGE_UUID)
        with _patched_message_query(message):
            assert handler.compute() == []

    def test_null_recipient_skipped(self) -> None:
        message = SimpleNamespace(
            id=MESSAGE_UUID,
            sender=_canvas_user(is_staff=False, subclass_id=PATIENT_UUID),
            recipient=None,
        )
        handler = _make_handler(MESSAGE_UUID)
        with _patched_message_query(message):
            assert handler.compute() == []

    def test_message_not_found_skipped(self) -> None:
        handler = _make_handler(MESSAGE_UUID)
        with _patched_message_query(None):
            assert handler.compute() == []
