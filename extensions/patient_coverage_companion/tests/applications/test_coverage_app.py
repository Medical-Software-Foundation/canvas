"""Tests for the CoverageCompanionApp Application class."""

from types import SimpleNamespace
from unittest.mock import patch

from canvas_generated.messages.effects_pb2 import EffectType

from patient_coverage_companion.applications.coverage_app import CoverageCompanionApp


def _make_app(patient_id: str = "abc-patient") -> CoverageCompanionApp:
    """Build a CoverageCompanionApp with a stubbed event context."""
    app = CoverageCompanionApp.__new__(CoverageCompanionApp)
    app.event = SimpleNamespace(context={"patient": {"id": patient_id}})
    return app


def test_on_open_returns_launch_modal_with_patient_id() -> None:
    """on_open emits a LaunchModalEffect pointing at the plugin's SimpleAPI
    URL, passing patient_id on the query string so the iframe can scope to it."""
    app = _make_app("patient-123")
    effect = app.on_open()
    assert effect.type == EffectType.LAUNCH_MODAL
    assert "patient_coverage_companion" in effect.payload
    assert "patient_id=patient-123" in effect.payload


def test_on_open_handles_missing_patient_context() -> None:
    """If the event context has no patient, on_open still emits an effect with
    an empty patient_id rather than raising — the iframe surfaces the error
    to the staff user."""
    app = CoverageCompanionApp.__new__(CoverageCompanionApp)
    app.event = SimpleNamespace(context={})
    effect = app.on_open()
    assert effect.type == EffectType.LAUNCH_MODAL
    assert "patient_id=" in effect.payload
