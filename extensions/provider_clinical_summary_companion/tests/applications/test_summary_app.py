"""Tests for provider_clinical_summary_companion.applications.summary_app."""
import json
from types import SimpleNamespace

from canvas_sdk.effects import EffectType

from provider_clinical_summary_companion.applications.summary_app import ClinicalSummaryApp

PATIENT_UUID = "00000000-0000-0000-0000-0000000000aa"


def _make_app(context: dict) -> ClinicalSummaryApp:
    app = ClinicalSummaryApp.__new__(ClinicalSummaryApp)
    app.event = SimpleNamespace(context=context)
    return app


class TestClinicalSummaryAppOnOpen:
    def test_returns_launch_modal_effect_with_patient_id(self) -> None:
        app = _make_app({"patient": {"id": PATIENT_UUID}})
        effect = app.on_open()

        assert effect.type == EffectType.LAUNCH_MODAL
        payload = json.loads(effect.payload)["data"]
        assert payload["url"] == (
            "/plugin-io/api/provider_clinical_summary_companion/app/"
            f"?patient_id={PATIENT_UUID}"
        )
        assert payload["target"] == "default_modal"

    def test_missing_patient_uses_empty_string(self) -> None:
        app = _make_app({})
        effect = app.on_open()
        payload = json.loads(effect.payload)["data"]
        assert payload["url"].endswith("?patient_id=")
