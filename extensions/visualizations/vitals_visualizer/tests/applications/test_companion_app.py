"""Tests for vitals_visualizer.applications.companion_app."""
import json
from types import SimpleNamespace

from canvas_sdk.effects import EffectType

from vitals_visualizer.applications.companion_app import (
    VitalsVisualizerCompanionApp,
)

PATIENT_UUID = "11111111-1111-1111-1111-111111111111"


class TestVitalsVisualizerCompanionApp:
    def test_on_open_includes_patient_id_in_url(self) -> None:
        app = VitalsVisualizerCompanionApp.__new__(VitalsVisualizerCompanionApp)
        app.event = SimpleNamespace(context={"patient": {"id": PATIENT_UUID}})
        effect = app.on_open()

        assert effect.type == EffectType.LAUNCH_MODAL
        data = json.loads(effect.payload)["data"]
        assert data["url"] == f"/plugin-io/api/vitals_visualizer/?patient={PATIENT_UUID}"
        assert data["target"] == "default_modal"

    def test_on_open_with_no_patient_context(self) -> None:
        app = VitalsVisualizerCompanionApp.__new__(VitalsVisualizerCompanionApp)
        app.event = SimpleNamespace(context={})
        effect = app.on_open()
        data = json.loads(effect.payload)["data"]
        assert data["url"].endswith("?patient=")
