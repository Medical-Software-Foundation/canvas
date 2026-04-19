"""Tests for provider_patient_messages_companion.applications.messages_app."""
import json

from canvas_sdk.effects import EffectType

from provider_patient_messages_companion.applications.messages_app import MessagesApp


class TestMessagesApp:
    def test_on_open_returns_launch_modal_effect(self) -> None:
        app = MessagesApp.__new__(MessagesApp)
        effect = app.on_open()

        assert effect.type == EffectType.LAUNCH_MODAL
        data = json.loads(effect.payload)["data"]
        assert data["url"] == "/plugin-io/api/provider_patient_messages_companion/app/"
        assert data["target"] == "default_modal"
