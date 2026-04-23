"""Tests for provider_task_dashboard_companion.applications.task_dashboard_app."""
import json
from types import SimpleNamespace

from canvas_sdk.effects import EffectType

from provider_task_dashboard_companion.applications.task_dashboard_app import (
    PatientTaskDashboardApp,
    TaskDashboardApp,
)

PATIENT_UUID = "11111111-1111-1111-1111-111111111111"


class TestTaskDashboardApp:
    def test_on_open_returns_launch_modal_effect(self) -> None:
        app = TaskDashboardApp.__new__(TaskDashboardApp)
        effect = app.on_open()

        assert effect.type == EffectType.LAUNCH_MODAL
        data = json.loads(effect.payload)["data"]
        assert data["url"] == "/plugin-io/api/provider_task_dashboard_companion/app/"
        assert data["target"] == "default_modal"


class TestPatientTaskDashboardApp:
    def test_on_open_includes_patient_id_in_url(self) -> None:
        app = PatientTaskDashboardApp.__new__(PatientTaskDashboardApp)
        app.event = SimpleNamespace(context={"patient": {"id": PATIENT_UUID}})
        effect = app.on_open()

        assert effect.type == EffectType.LAUNCH_MODAL
        data = json.loads(effect.payload)["data"]
        assert data["url"] == (
            "/plugin-io/api/provider_task_dashboard_companion/app/?patient_id="
            + PATIENT_UUID
        )
        assert data["target"] == "default_modal"

    def test_on_open_with_no_patient_context(self) -> None:
        # Defensive: the patient-specific surface should always provide context,
        # but the plugin doesn't crash if it doesn't.
        app = PatientTaskDashboardApp.__new__(PatientTaskDashboardApp)
        app.event = SimpleNamespace(context={})
        effect = app.on_open()
        data = json.loads(effect.payload)["data"]
        assert data["url"].endswith("?patient_id=")
