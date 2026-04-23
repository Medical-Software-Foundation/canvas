"""Tests for provider_schedule_companion.applications.schedule_app."""
import json

from canvas_sdk.effects import EffectType

from provider_schedule_companion.applications.schedule_app import ScheduleApp


class TestScheduleApp:
    def test_on_open_returns_launch_modal_effect(self) -> None:
        app = ScheduleApp.__new__(ScheduleApp)  # bypass pydantic __init__
        effect = app.on_open()

        assert effect.type == EffectType.LAUNCH_MODAL
        payload = json.loads(effect.payload)["data"]
        assert payload["url"] == "/plugin-io/api/provider_schedule_companion/app/"
        assert payload["target"] == "default_modal"
