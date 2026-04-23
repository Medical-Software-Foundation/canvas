"""Tests for provider_note_vitals_companion.applications.vitals_app."""
import json
from types import SimpleNamespace

from canvas_sdk.effects import EffectType

from provider_note_vitals_companion.applications.vitals_app import VitalsApp

NOTE_UUID = "00000000-0000-0000-0000-00000000aaaa"


def _make_app(context: dict) -> VitalsApp:
    app = VitalsApp.__new__(VitalsApp)  # bypass pydantic __init__
    app.event = SimpleNamespace(context=context)
    return app


class TestVitalsAppOnOpen:
    def test_returns_launch_modal_effect_with_note_id(self) -> None:
        app = _make_app({"note": {"id": NOTE_UUID}})
        effect = app.on_open()

        assert effect.type == EffectType.LAUNCH_MODAL
        payload = json.loads(effect.payload)["data"]
        assert payload["url"] == (
            "/plugin-io/api/provider_note_vitals_companion/app/"
            f"?note_id={NOTE_UUID}"
        )
        assert payload["target"] == "default_modal"

    def test_missing_note_context_uses_empty_note_id(self) -> None:
        app = _make_app({})
        effect = app.on_open()
        payload = json.loads(effect.payload)["data"]
        assert payload["url"] == (
            "/plugin-io/api/provider_note_vitals_companion/app/?note_id="
        )
