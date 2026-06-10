"""Tests for the PatientDocumentCaptureApp Application."""

import json
from unittest.mock import PropertyMock, patch

import pytest
from canvas_sdk.effects import EffectType
from canvas_sdk.effects.launch_modal import LaunchModalEffect

from capture.applications.document_app import (
    PatientDocumentCaptureApp,
    PatientDocumentCaptureCompanionApp,
)


@pytest.fixture
def app():
    return PatientDocumentCaptureApp.__new__(PatientDocumentCaptureApp)


def _patch_context(value):
    return patch.object(
        PatientDocumentCaptureApp, "context", new_callable=PropertyMock,
        return_value=value,
    )


def test_on_open_returns_launch_modal_effect(app) -> None:
    with _patch_context({"patient": {"id": "patient-123"}}), patch(
        "capture.applications.document_app.render_to_string"
    ) as mock_render:
        mock_render.return_value = "<html></html>"
        effect = app.on_open()
        assert effect.type == EffectType.LAUNCH_MODAL


def test_on_open_injects_patient_id_and_api_base(app) -> None:
    with _patch_context({"patient": {"id": "patient-123"}}), patch(
        "capture.applications.document_app.render_to_string"
    ) as mock_render:
        mock_render.return_value = "<html></html>"
        app.on_open()

        template, context = mock_render.call_args[0]
        assert template == "templates/upload_modal.html"
        assert context["patient_id"] == "patient-123"
        assert context["api_base"] == "/plugin-io/api/capture"
        assert "cache_bust" in context
        assert context["show_close"] is True  # chart modal keeps its own close X


def test_on_open_handles_missing_patient(app) -> None:
    with _patch_context({}), patch(
        "capture.applications.document_app.render_to_string"
    ) as mock_render:
        mock_render.return_value = "<html></html>"
        app.on_open()
        _, context = mock_render.call_args[0]
        assert context["patient_id"] == ""


# ---- Provider Companion app (same workflow, different surface) ----

@pytest.fixture
def companion():
    return PatientDocumentCaptureCompanionApp.__new__(PatientDocumentCaptureCompanionApp)


def test_companion_is_distinct_application(companion) -> None:
    """The companion is a distinct registered app built on the same base class."""
    assert isinstance(companion, PatientDocumentCaptureApp)
    parent = PatientDocumentCaptureApp.__new__(PatientDocumentCaptureApp)
    assert companion.identifier != parent.identifier


def test_companion_on_open_launches_served_url_with_patient(companion) -> None:
    """Companion launches the served /documents/ui iframe (URL, not inline content)."""
    with patch.object(
        PatientDocumentCaptureCompanionApp, "context", new_callable=PropertyMock,
        return_value={"patient": {"id": "patient-456"}},
    ):
        effect = companion.on_open()
        assert effect.type == EffectType.LAUNCH_MODAL
        data = json.loads(effect.payload)["data"]
        assert data["content"] is None
        assert data["url"].startswith(
            "/plugin-io/api/capture/documents/ui?patient_id=patient-456&v="
        )
        assert data["target"] == LaunchModalEffect.TargetType.DEFAULT_MODAL.value


def test_companion_on_open_handles_missing_patient(companion) -> None:
    with patch.object(
        PatientDocumentCaptureCompanionApp, "context", new_callable=PropertyMock,
        return_value={},
    ):
        effect = companion.on_open()
        data = json.loads(effect.payload)["data"]
        assert "patient_id=&v=" in data["url"]
