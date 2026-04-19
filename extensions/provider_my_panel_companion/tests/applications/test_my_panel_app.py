"""Tests for provider_my_panel_companion.applications.my_panel_app."""
import json

from canvas_sdk.effects import EffectType

from provider_my_panel_companion.applications.my_panel_app import MyPanelApp


class TestMyPanelApp:
    def test_on_open_returns_launch_modal_effect(self) -> None:
        app = MyPanelApp.__new__(MyPanelApp)
        effect = app.on_open()

        assert effect.type == EffectType.LAUNCH_MODAL
        data = json.loads(effect.payload)["data"]
        assert data["url"] == "/plugin-io/api/provider_my_panel_companion/app/"
        assert data["target"] == "default_modal"
