"""Tests for the PatientDocumentCaptureApp Application."""

from unittest.mock import PropertyMock, patch

import pytest
from canvas_sdk.effects import EffectType

from patient_document_capture.applications.document_app import (
    PatientDocumentCaptureApp,
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
        "patient_document_capture.applications.document_app.render_to_string"
    ) as mock_render:
        mock_render.return_value = "<html></html>"
        effect = app.on_open()
        assert effect.type == EffectType.LAUNCH_MODAL


def test_on_open_injects_patient_id_and_api_base(app) -> None:
    with _patch_context({"patient": {"id": "patient-123"}}), patch(
        "patient_document_capture.applications.document_app.render_to_string"
    ) as mock_render:
        mock_render.return_value = "<html></html>"
        app.on_open()

        template, context = mock_render.call_args[0]
        assert template == "templates/upload_modal.html"
        assert context["patient_id"] == "patient-123"
        assert context["api_base"] == "/plugin-io/api/patient_document_capture"
        assert "cache_bust" in context


def test_on_open_handles_missing_patient(app) -> None:
    with _patch_context({}), patch(
        "patient_document_capture.applications.document_app.render_to_string"
    ) as mock_render:
        mock_render.return_value = "<html></html>"
        app.on_open()
        _, context = mock_render.call_args[0]
        assert context["patient_id"] == ""
