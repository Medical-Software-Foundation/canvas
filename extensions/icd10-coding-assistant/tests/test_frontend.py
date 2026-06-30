"""Tests for ICD10FrontendAPI."""

from unittest.mock import MagicMock, patch

import pytest

from icd10_coding_assistant.api.icd10_frontend import ICD10FrontendAPI


class DummyFrontendEvent:
    """Minimal event dict for ICD10FrontendAPI construction."""

    def __init__(self) -> None:
        self.context: dict[str, object] = {"method": "GET", "path": "/ui/icd10-coding"}


@pytest.fixture
def frontend_instance() -> ICD10FrontendAPI:
    api = ICD10FrontendAPI(DummyFrontendEvent())
    api.request = MagicMock()
    api.request.query_params = {}
    api.request.headers = {}
    return api


def test_get_returns_400_when_no_patient_id(
    frontend_instance: ICD10FrontendAPI,
) -> None:
    frontend_instance.request.query_params = {}

    with patch(
        "icd10_coding_assistant.api.icd10_frontend.render_to_string", return_value=""
    ):
        result = frontend_instance.get()

    assert len(result) == 1
    assert result[0].status_code == 400


def test_get_returns_html_with_patient_id(frontend_instance: ICD10FrontendAPI) -> None:
    frontend_instance.request.query_params = {"patient_id": "patient-abc"}
    frontend_instance.request.headers = {"host": "test.canvasmedical.com"}

    rendered_html = "<html>ICD-10 Coding Assistant patient-abc</html>"
    with patch(
        "icd10_coding_assistant.api.icd10_frontend.render_to_string",
        return_value=rendered_html,
    ) as mock_render:
        result = frontend_instance.get()

    assert len(result) == 1
    assert result[0].status_code == 200
    assert b"ICD-10 Coding Assistant" in result[0].content

    # Verify render_to_string was called with patient context
    call_context = mock_render.call_args[0][1]
    assert call_context["patient_id"] == "patient-abc"
    assert call_context["host"] == "test.canvasmedical.com"


def test_get_css_returns_css_content_type(frontend_instance: ICD10FrontendAPI) -> None:
    with patch(
        "icd10_coding_assistant.api.icd10_frontend.render_to_string",
        return_value="body { margin: 0; }",
    ):
        result = frontend_instance.get_css()
    assert len(result) == 1
    response = result[0]
    assert response.status_code == 200
    # content_type is stored in the headers dict by the Response constructor
    assert response.headers.get("Content-Type") == "text/css"


def test_get_script_returns_js_content_type(
    frontend_instance: ICD10FrontendAPI,
) -> None:
    with patch(
        "icd10_coding_assistant.api.icd10_frontend.render_to_string",
        return_value="function loadConditions() {}",
    ):
        result = frontend_instance.get_script()
    assert len(result) == 1
    response = result[0]
    assert response.status_code == 200
    assert response.headers.get("Content-Type") == "application/javascript"
