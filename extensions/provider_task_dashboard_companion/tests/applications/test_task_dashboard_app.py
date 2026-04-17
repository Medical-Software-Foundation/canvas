"""Tests for provider_task_dashboard_companion.applications.task_dashboard_app."""
import json

from canvas_sdk.effects import EffectType

from provider_task_dashboard_companion.applications.task_dashboard_app import TaskDashboardApp


class TestTaskDashboardApp:
    def test_on_open_returns_launch_modal_effect(self) -> None:
        app = TaskDashboardApp.__new__(TaskDashboardApp)
        effect = app.on_open()

        assert effect.type == EffectType.LAUNCH_MODAL
        data = json.loads(effect.payload)["data"]
        assert data["url"] == "/plugin-io/api/provider_task_dashboard_companion/app/"
        assert data["target"] == "default_modal"
