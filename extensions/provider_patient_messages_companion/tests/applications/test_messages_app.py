"""Tests for provider_patient_messages_companion.applications.messages_app."""
import json
from types import SimpleNamespace

from canvas_sdk.effects import EffectType

from provider_patient_messages_companion.applications.messages_app import (
    MessagesApp,
    PatientMessagesApp,
)

PATIENT_UUID = "11111111-1111-1111-1111-111111111111"


class TestMessagesApp:
    def test_on_open_returns_launch_modal_effect(self) -> None:
        app = MessagesApp.__new__(MessagesApp)
        effect = app.on_open()

        assert effect.type == EffectType.LAUNCH_MODAL
        data = json.loads(effect.payload)["data"]
        assert data["url"] == "/plugin-io/api/provider_patient_messages_companion/app/"
        assert data["target"] == "default_modal"


class TestPatientMessagesApp:
    def test_on_open_includes_patient_id_in_url(self) -> None:
        app = PatientMessagesApp.__new__(PatientMessagesApp)
        app.event = SimpleNamespace(context={"patient": {"id": PATIENT_UUID}})
        effect = app.on_open()

        assert effect.type == EffectType.LAUNCH_MODAL
        data = json.loads(effect.payload)["data"]
        assert data["url"] == (
            "/plugin-io/api/provider_patient_messages_companion/app/?patient_id="
            + PATIENT_UUID
        )

    def test_on_open_with_no_patient_context(self) -> None:
        app = PatientMessagesApp.__new__(PatientMessagesApp)
        app.event = SimpleNamespace(context={})
        effect = app.on_open()
        data = json.loads(effect.payload)["data"]
        assert data["url"].endswith("?patient_id=")
