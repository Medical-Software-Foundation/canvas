"""Tests for provider_register_patient_companion.applications.register_patient_app."""
import json

from canvas_sdk.effects import EffectType

from provider_register_patient_companion.applications.register_patient_app import (
    RegisterPatientApp,
)


class TestRegisterPatientApp:
    def test_on_open_returns_launch_modal_effect(self) -> None:
        app = RegisterPatientApp.__new__(RegisterPatientApp)
        effect = app.on_open()

        assert effect.type == EffectType.LAUNCH_MODAL
        payload = json.loads(effect.payload)["data"]
        assert payload["url"] == "/plugin-io/api/provider_register_patient_companion/app/"
        assert payload["target"] == "default_modal"
