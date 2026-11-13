"""Tests for visit_summaries.helpers.llm_service."""
from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest

import json

from visit_summaries.helpers.llm_service import (
    _build_client,
    _parse_llm_json,
    generate_avs,
    generate_previous_visit_summary,
    generate_since_last_visit_summary,
    render_missing_config_html,
    sanitize_llm_html,
    validate_llm_secrets,
)


def _make_llm_response(text: str, code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.code = code
    resp.response = text
    return resp


SECRETS_ANTHROPIC = {"LLM_PROVIDER": "anthropic", "LLM_API_KEY": "key-abc", "LLM_MODEL": ""}
SECRETS_OPENAI = {"LLM_PROVIDER": "openai", "LLM_API_KEY": "key-xyz", "LLM_MODEL": "gpt-4o"}
SECRETS_GOOGLE = {"LLM_PROVIDER": "google", "LLM_API_KEY": "key-ggl", "LLM_MODEL": ""}


# ---------------------------------------------------------------------------
# validate_llm_secrets
# ---------------------------------------------------------------------------

def test_validate_returns_empty_when_all_set():
    assert validate_llm_secrets(SECRETS_ANTHROPIC) == []


def test_validate_returns_missing_provider():
    assert "LLM_PROVIDER" in validate_llm_secrets({"LLM_API_KEY": "k"})


def test_validate_returns_missing_api_key():
    assert "LLM_API_KEY" in validate_llm_secrets({"LLM_PROVIDER": "anthropic"})


def test_validate_returns_both_when_empty():
    missing = validate_llm_secrets({})
    assert "LLM_PROVIDER" in missing
    assert "LLM_API_KEY" in missing


def test_validate_rejects_invalid_provider():
    assert "LLM_PROVIDER" in validate_llm_secrets({"LLM_PROVIDER": "invalid", "LLM_API_KEY": "k"})


def test_validate_skips_api_key_for_mock():
    assert validate_llm_secrets({"LLM_PROVIDER": "mock", "LLM_API_KEY": ""}) == []


def test_validate_accepts_whitespace_trimmed_values():
    assert validate_llm_secrets({"LLM_PROVIDER": " anthropic ", "LLM_API_KEY": " key "}) == []


# ---------------------------------------------------------------------------
# render_missing_config_html
# ---------------------------------------------------------------------------

def test_render_missing_config_lists_keys():
    html = render_missing_config_html(["LLM_PROVIDER", "LLM_API_KEY"])
    assert "LLM_PROVIDER" in html
    assert "LLM_API_KEY" in html
    assert "Configuration Required" in html


def test_render_missing_config_has_inline_styles():
    html = render_missing_config_html(["LLM_API_KEY"])
    assert 'style="' in html


# ---------------------------------------------------------------------------
# _build_client
# ---------------------------------------------------------------------------

def test_build_client_anthropic():
    with patch("visit_summaries.helpers.llm_service.LlmAnthropic") as MockCls:
        _build_client(SECRETS_ANTHROPIC)
        MockCls.assert_called_once()


def test_build_client_openai():
    with patch("visit_summaries.helpers.llm_service.LlmOpenai") as MockCls:
        _build_client(SECRETS_OPENAI)
        MockCls.assert_called_once()


def test_build_client_google():
    with patch("visit_summaries.helpers.llm_service.LlmGoogle") as MockCls:
        _build_client(SECRETS_GOOGLE)
        MockCls.assert_called_once()


# ---------------------------------------------------------------------------
# generate_previous_visit_summary
# ---------------------------------------------------------------------------

def test_generate_previous_visit_summary_success():
    llm_json = json.dumps({
        "chief_complaint": "Lower back pain for two weeks",
        "diagnoses": ["persistent, worsening with sitting"],
        "plan_items": ["Continue PT twice weekly"],
    })
    mock_client = MagicMock()
    mock_client.attempt_requests.return_value = [_make_llm_response(llm_json)]

    with patch("visit_summaries.helpers.llm_service._build_client", return_value=mock_client):
        result = generate_previous_visit_summary(
            "Note context here",
            SECRETS_ANTHROPIC,
            chief_complaint="Back pain",
            diagnoses=[{"code": "M54.50", "display": "Low back pain"}],
            medications=[],
            plan_items=["Continue PT"],
            vitals={"systolic": "130", "diastolic": "85"},
        )

    assert "Lower back pain" in result
    assert "M54.50" in result
    assert "130/85" in result
    mock_client.set_system_prompt.assert_called_once()
    mock_client.attempt_requests.assert_called_once_with(attempts=2)


def test_generate_previous_visit_summary_llm_error():
    """On LLM failure, renderer uses raw extracted data as fallback."""
    mock_client = MagicMock()
    mock_client.attempt_requests.return_value = [_make_llm_response("Server error", code=500)]

    with patch("visit_summaries.helpers.llm_service._build_client", return_value=mock_client):
        result = generate_previous_visit_summary(
            "Note context",
            SECRETS_ANTHROPIC,
            chief_complaint="Headache",
            diagnoses=[{"code": "R51", "display": "Headache"}],
        )

    assert "Headache" in result
    assert "R51" in result


# ---------------------------------------------------------------------------
# generate_since_last_visit_summary
# ---------------------------------------------------------------------------

def test_generate_since_last_visit_summary_success():
    llm_json = json.dumps({"lab_interpretation": "HbA1c trending down"})
    mock_client = MagicMock()
    mock_client.attempt_requests.return_value = [_make_llm_response(llm_json)]

    with patch("visit_summaries.helpers.llm_service._build_client", return_value=mock_client):
        result = generate_since_last_visit_summary(
            "Interim context",
            SECRETS_OPENAI,
            lab_reports=[{"name": "HbA1c", "value": "6.8", "units": "%", "reference_range": "< 5.7", "flag": "H"}],
            completed_tasks=["Annual labs"],
        )

    assert "HbA1c" in result
    assert "trending down" in result
    assert "Annual labs" in result


def test_generate_since_last_visit_summary_error():
    """On LLM failure, renderer uses raw extracted data as fallback."""
    mock_client = MagicMock()
    mock_client.attempt_requests.return_value = [_make_llm_response("Timeout", code=503)]

    with patch("visit_summaries.helpers.llm_service._build_client", return_value=mock_client):
        result = generate_since_last_visit_summary(
            "Interim context",
            SECRETS_OPENAI,
            completed_tasks=["Eye exam referral"],
        )

    assert "Eye exam referral" in result


# ---------------------------------------------------------------------------
# generate_avs
# ---------------------------------------------------------------------------

def test_generate_avs_success():
    llm_json = json.dumps({
        "discussion": "We talked about your back pain.",
        "medications": ["Take one tablet every 6 hours with food"],
        "next_steps": ["Come back in 4 weeks"],
        "warning_signs": ["Numbness in your legs"],
    })
    mock_client = MagicMock()
    mock_client.attempt_requests.return_value = [_make_llm_response(llm_json)]

    patient_info = {"first_name": "Jane", "last_name": "Doe", "visit_date": "January 15, 2025", "provider_name": "Dr. Smith"}

    with patch("visit_summaries.helpers.llm_service._build_client", return_value=mock_client):
        result = generate_avs(
            "Note context",
            patient_info,
            SECRETS_ANTHROPIC,
            medications=[{"name": "Ibuprofen", "dose": "400mg", "sig": "Q6H"}],
            plan_items=["Follow up in 4 weeks"],
        )

    assert "Hi Jane," in result
    assert "January 15, 2025" in result
    assert "Dr. Smith" in result
    assert "back pain" in result
    assert "Ibuprofen" in result
    assert "Numbness in your legs" in result
    call_args = mock_client.set_user_prompt.call_args[0][0][0]
    assert "Jane" in call_args


def test_generate_avs_error():
    """On LLM failure, renderer uses raw extracted data and defaults."""
    mock_client = MagicMock()
    mock_client.attempt_requests.return_value = [_make_llm_response("error", code=400)]

    patient_info = {"first_name": "Bob", "provider_name": "Dr. Lee"}

    with patch("visit_summaries.helpers.llm_service._build_client", return_value=mock_client):
        result = generate_avs(
            "Note context",
            patient_info,
            SECRETS_ANTHROPIC,
            plan_items=["Rest for 48 hours"],
        )

    assert "Hi Bob," in result
    assert "Dr. Lee" in result
    assert "Rest for 48 hours" in result


# ---------------------------------------------------------------------------
# sanitize_llm_html
# ---------------------------------------------------------------------------

def test_sanitize_removes_script_tags():
    html = '<div>Hello</div><script>alert("xss")</script><p>End</p>'
    result = sanitize_llm_html(html)
    assert "<script" not in result
    assert "<div>Hello</div>" in result
    assert "<p>End</p>" in result


def test_sanitize_removes_iframe_tags():
    html = '<div>Content</div><iframe src="evil.com"></iframe>'
    result = sanitize_llm_html(html)
    assert "<iframe" not in result
    assert "<div>Content</div>" in result


def test_sanitize_removes_event_handlers():
    html = '<div onmouseover="alert(1)">Hover me</div>'
    result = sanitize_llm_html(html)
    assert "onmouseover" not in result
    assert "Hover me</div>" in result


def test_sanitize_removes_javascript_urls():
    html = '<a href="javascript:alert(1)">Click</a>'
    result = sanitize_llm_html(html)
    assert "javascript:" not in result


def test_sanitize_preserves_safe_html():
    html = '<div class="summary"><h3>Diagnosis</h3><ul><li>Hypertension</li></ul></div>'
    result = sanitize_llm_html(html)
    assert result == html


# ---------------------------------------------------------------------------
# mock provider path
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# missing config returns warning HTML
# ---------------------------------------------------------------------------

def test_generate_previous_visit_missing_secrets_returns_warning():
    result = generate_previous_visit_summary("context", {})
    assert "Configuration Required" in result
    assert "LLM_PROVIDER" in result


def test_generate_since_last_visit_missing_secrets_returns_warning():
    result = generate_since_last_visit_summary("context", {})
    assert "Configuration Required" in result


def test_generate_avs_missing_secrets_returns_warning():
    result = generate_avs("context", {}, {})
    assert "Configuration Required" in result


def test_generate_previous_visit_missing_api_key_only():
    result = generate_previous_visit_summary("context", {"LLM_PROVIDER": "anthropic"})
    assert "LLM_API_KEY" in result
    assert "Configuration Required" in result


# ---------------------------------------------------------------------------
# mock provider path
# ---------------------------------------------------------------------------

SECRETS_MOCK = {"LLM_PROVIDER": "mock", "LLM_API_KEY": "", "LLM_MODEL": ""}


def test_generate_previous_visit_mock_provider():
    result = generate_previous_visit_summary("some context", SECRETS_MOCK)
    assert "Chief Complaint" in result
    assert "Mock data" in result


def test_generate_since_last_visit_mock_provider():
    result = generate_since_last_visit_summary("some context", SECRETS_MOCK)
    assert "Lab Results" in result
    assert "Mock data" in result


def test_generate_avs_mock_provider():
    patient_info = {"first_name": "Alice", "visit_date": "March 1, 2026"}
    result = generate_avs("some context", patient_info, SECRETS_MOCK)
    assert "Alice" in result
    assert "March 1, 2026" in result
    assert "Mock data" in result


# ---------------------------------------------------------------------------
# sanitize integration
# ---------------------------------------------------------------------------

def test_xss_in_json_values_escaped():
    """Verify that HTML in LLM JSON values is escaped by the renderer."""
    malicious_json = json.dumps({
        "chief_complaint": '<script>alert("xss")</script>Headache',
        "diagnoses": ['<img src=x onerror="alert(1)">'],
        "plan_items": [],
    })
    mock_client = MagicMock()
    mock_client.attempt_requests.return_value = [_make_llm_response(malicious_json)]

    with patch("visit_summaries.helpers.llm_service._build_client", return_value=mock_client):
        result = generate_previous_visit_summary(
            "Note context",
            SECRETS_ANTHROPIC,
            chief_complaint="Headache",
            diagnoses=[{"code": "R51", "display": "Headache"}],
        )

    assert "<script>" not in result
    assert 'onerror="' not in result
    assert "&lt;script&gt;" in result


def test_parse_llm_json_strips_markdown_fences():
    raw = '```json\n{"key": "value"}\n```'
    result = _parse_llm_json(raw)
    assert result == {"key": "value"}


def test_parse_llm_json_plain():
    raw = '{"key": "value"}'
    result = _parse_llm_json(raw)
    assert result == {"key": "value"}
