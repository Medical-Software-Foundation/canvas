"""Tests for visit_summaries.protocols.summary_api."""
from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest

from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse


def _make_loading_api(query_params=None, secrets=None):
    """Return a SummaryApi instance with mocked request and secrets."""
    from visit_summaries.protocols.summary_api import SummaryApi

    handler = SummaryApi.__new__(SummaryApi)
    handler.request = MagicMock()
    handler.request.query_params = query_params or {}
    handler.secrets = secrets or {"LLM_PROVIDER": "anthropic", "LLM_API_KEY": "k", "LLM_MODEL": ""}
    return handler


def _make_generate_api(query_params=None, secrets=None):
    """Return a SummaryGenerateApi instance with mocked request and secrets."""
    from visit_summaries.protocols.summary_api import SummaryGenerateApi

    handler = SummaryGenerateApi.__new__(SummaryGenerateApi)
    handler.request = MagicMock()
    handler.request.query_params = query_params or {}
    handler.secrets = secrets or {"LLM_PROVIDER": "anthropic", "LLM_API_KEY": "k", "LLM_MODEL": ""}
    return handler


VALID_SECRETS = {"LLM_PROVIDER": "anthropic", "LLM_API_KEY": "key-abc", "LLM_MODEL": ""}


# ---------------------------------------------------------------------------
# Loading page endpoints (SummaryApi)
# ---------------------------------------------------------------------------

def test_previous_visit_loading_returns_html():
    api = _make_loading_api({"note_id": "1", "patient_id": "p1"})
    with patch("visit_summaries.protocols.summary_api.render_to_string", return_value="<html>loading</html>"):
        result = api.previous_visit_loading()
    assert len(result) == 1
    assert isinstance(result[0], HTMLResponse)


def test_since_last_visit_loading_returns_html():
    api = _make_loading_api({"note_id": "1", "patient_id": "p1"})
    with patch("visit_summaries.protocols.summary_api.render_to_string", return_value="<html>loading</html>"):
        result = api.since_last_visit_loading()
    assert isinstance(result[0], HTMLResponse)


def test_avs_loading_returns_html():
    api = _make_loading_api({"note_id": "1", "patient_id": "p1"})
    with patch("visit_summaries.protocols.summary_api.render_to_string", return_value="<html>loading</html>"):
        result = api.avs_loading()
    assert isinstance(result[0], HTMLResponse)


def test_loading_page_passes_generate_url():
    captured = {}
    def capture(template, context):
        captured.update(context)
        return "<html/>"

    api = _make_loading_api({"note_id": "42", "patient_id": "p99"})
    with patch("visit_summaries.protocols.summary_api.render_to_string", side_effect=capture):
        api.previous_visit_loading()
    assert "42" in captured["generate_url"]
    assert "p99" in captured["generate_url"]
    assert "summary-gen" in captured["generate_url"]


# ---------------------------------------------------------------------------
# Generate endpoints (SummaryGenerateApi)
# ---------------------------------------------------------------------------

def test_generate_previous_visit_missing_secrets():
    api = _make_generate_api({"note_id": "1", "patient_id": "p1"}, secrets={})
    with (
        patch("visit_summaries.protocols.summary_api.validate_llm_secrets", return_value=["LLM_PROVIDER"]),
        patch("visit_summaries.protocols.summary_api.render_missing_config_html", return_value="<div>Config Required</div>"),
    ):
        result = api.generate_previous_visit()
    assert isinstance(result[0], JSONResponse)
    assert b"Config Required" in result[0].content


def test_generate_previous_visit_no_prior_note():
    api = _make_generate_api({"note_id": "1", "patient_id": "p1"}, secrets=VALID_SECRETS)
    with patch("visit_summaries.protocols.summary_api.get_most_recent_locked_note", return_value=None):
        result = api.generate_previous_visit()
    assert b"no-data" in result[0].content


def test_generate_previous_visit_success():
    api = _make_generate_api({"note_id": "1", "patient_id": "p1"}, secrets=VALID_SECRETS)
    mock_note = MagicMock()
    mock_note.datetime_of_service = "2025-03-01T09:00:00"
    with (
        patch("visit_summaries.protocols.summary_api.get_most_recent_locked_note", return_value=mock_note),
        patch("visit_summaries.protocols.summary_api.build_note_context_for_llm", return_value="ctx"),
        patch("visit_summaries.protocols.summary_api.generate_previous_visit_summary", return_value="<div>Summary</div>"),
    ):
        result = api.generate_previous_visit()
    assert b"Summary" in result[0].content
    assert b"Mar 1, 2025" in result[0].content


def test_generate_since_last_visit_missing_secrets():
    api = _make_generate_api({"note_id": "1", "patient_id": "p1"}, secrets={})
    with (
        patch("visit_summaries.protocols.summary_api.validate_llm_secrets", return_value=["LLM_PROVIDER"]),
        patch("visit_summaries.protocols.summary_api.render_missing_config_html", return_value="<div>Config Required</div>"),
    ):
        result = api.generate_since_last_visit()
    assert b"Config Required" in result[0].content


def test_generate_since_last_visit_no_prior_note():
    api = _make_generate_api({"note_id": "1", "patient_id": "p1"}, secrets=VALID_SECRETS)
    with patch("visit_summaries.protocols.summary_api.get_most_recent_locked_note", return_value=None):
        result = api.generate_since_last_visit()
    assert b"no-data" in result[0].content


def test_generate_since_last_visit_success():
    api = _make_generate_api({"note_id": "1", "patient_id": "p1"}, secrets=VALID_SECRETS)
    mock_note = MagicMock()
    mock_note.datetime_of_service = "2025-02-01T09:00:00"
    with (
        patch("visit_summaries.protocols.summary_api.get_most_recent_locked_note", return_value=mock_note),
        patch("visit_summaries.protocols.summary_api.Note") as MockNote,
        patch("visit_summaries.protocols.summary_api.build_interim_context_for_llm", return_value="interim"),
        patch("visit_summaries.protocols.summary_api.generate_since_last_visit_summary", return_value="<div>Interim</div>"),
    ):
        mock_current = MagicMock()
        mock_current.datetime_of_service = "2025-03-01T09:00:00"
        MockNote.objects.filter.return_value.first.return_value = mock_current
        result = api.generate_since_last_visit()
    assert b"Interim" in result[0].content


def test_generate_avs_missing_secrets():
    api = _make_generate_api({"note_id": "1", "patient_id": "p1"}, secrets={})
    with (
        patch("visit_summaries.protocols.summary_api.validate_llm_secrets", return_value=["LLM_API_KEY"]),
        patch("visit_summaries.protocols.summary_api.render_missing_config_html", return_value="<div>Config Required</div>"),
    ):
        result = api.generate_avs_endpoint()
    assert b"Config Required" in result[0].content


def test_generate_avs_no_note():
    api = _make_generate_api({"note_id": "1", "patient_id": "p1"}, secrets=VALID_SECRETS)
    with patch("visit_summaries.protocols.summary_api.Note") as MockNote:
        MockNote.objects.select_related.return_value.filter.return_value.first.return_value = None
        result = api.generate_avs_endpoint()
    assert b"error" in result[0].content


def test_generate_avs_success():
    api = _make_generate_api({"note_id": "1", "patient_id": "p1"}, secrets=VALID_SECRETS)
    mock_provider = MagicMock()
    mock_provider.first_name = "Larry"
    mock_provider.last_name = "Weed"
    mock_note = MagicMock()
    mock_note.datetime_of_service = "2025-03-01T10:00:00"
    mock_note.provider = mock_provider
    mock_patient = MagicMock()
    mock_patient.first_name = "Alice"
    mock_patient.last_name = "Smith"
    mock_cmd = MagicMock()
    mock_cmd.schema_key = "plan"
    mock_cmd.data = {"narrative": "Rest"}
    with (
        patch("visit_summaries.protocols.summary_api.Note") as MockNote,
        patch("visit_summaries.protocols.summary_api.Patient") as MockPatient,
        patch("visit_summaries.protocols.summary_api.get_commands_for_note", return_value=[mock_cmd]),
        patch("visit_summaries.protocols.summary_api.build_note_context_for_llm", return_value="ctx"),
        patch("visit_summaries.protocols.summary_api.generate_avs", return_value="<div>Hi Alice</div>") as mock_gen,
    ):
        MockNote.objects.select_related.return_value.filter.return_value.first.return_value = mock_note
        MockPatient.objects.filter.return_value.first.return_value = mock_patient
        result = api.generate_avs_endpoint()
    assert b"Alice" in result[0].content
    call_args = mock_gen.call_args
    patient_info = call_args[1].get("patient_info") or call_args[0][1]
    assert patient_info.get("provider_name") == "Larry Weed"


def test_generate_avs_empty_note_guard():
    """AVS on a note with no commands returns a friendly message without calling LLM."""
    api = _make_generate_api({"note_id": "1", "patient_id": "p1"}, secrets=VALID_SECRETS)
    mock_note = MagicMock()
    mock_note.datetime_of_service = "2025-03-01T10:00:00"
    mock_note.provider = MagicMock(first_name="Larry", last_name="Weed")
    mock_patient = MagicMock(first_name="Alice", last_name="Smith")
    with (
        patch("visit_summaries.protocols.summary_api.Note") as MockNote,
        patch("visit_summaries.protocols.summary_api.Patient") as MockPatient,
        patch("visit_summaries.protocols.summary_api.get_commands_for_note", return_value=[]),
        patch("visit_summaries.protocols.summary_api.generate_avs") as mock_gen,
    ):
        MockNote.objects.select_related.return_value.filter.return_value.first.return_value = mock_note
        MockPatient.objects.filter.return_value.first.return_value = mock_patient
        result = api.generate_avs_endpoint()
    assert b"No commands have been documented" in result[0].content
    mock_gen.assert_not_called()


def test_generate_since_last_visit_returns_date_range():
    api = _make_generate_api({"note_id": "1", "patient_id": "p1"}, secrets=VALID_SECRETS)
    mock_note = MagicMock()
    mock_note.datetime_of_service = "2025-02-01T09:00:00"
    with (
        patch("visit_summaries.protocols.summary_api.get_most_recent_locked_note", return_value=mock_note),
        patch("visit_summaries.protocols.summary_api.Note") as MockNote,
        patch("visit_summaries.protocols.summary_api.build_interim_context_for_llm", return_value="interim"),
        patch("visit_summaries.protocols.summary_api.generate_since_last_visit_summary", return_value="<div>ok</div>"),
    ):
        mock_current = MagicMock()
        mock_current.datetime_of_service = "2025-02-01T09:00:00"
        MockNote.objects.filter.return_value.first.return_value = mock_current
        result = api.generate_since_last_visit()
    assert b"date_range" in result[0].content
    assert b"same day" in result[0].content


def test_generate_since_last_visit_no_current_note_falls_back_to_now():
    api = _make_generate_api({"note_id": "", "patient_id": "p1"}, secrets=VALID_SECRETS)
    mock_note = MagicMock()
    mock_note.datetime_of_service = "2025-02-01T09:00:00"
    with (
        patch("visit_summaries.protocols.summary_api.get_most_recent_locked_note", return_value=mock_note),
        patch("visit_summaries.protocols.summary_api.build_interim_context_for_llm", return_value="interim"),
        patch("visit_summaries.protocols.summary_api.generate_since_last_visit_summary", return_value="<div>ok</div>"),
    ):
        result = api.generate_since_last_visit()
    assert b"date_range" in result[0].content


def test_generate_avs_no_note_id():
    api = _make_generate_api({"note_id": "", "patient_id": "p1"}, secrets=VALID_SECRETS)
    result = api.generate_avs_endpoint()
    assert b"error" in result[0].content


def test_generate_avs_returns_subtitle():
    api = _make_generate_api({"note_id": "1", "patient_id": "p1"}, secrets=VALID_SECRETS)
    mock_note = MagicMock()
    mock_note.datetime_of_service = "2025-03-01T10:00:00"
    mock_note.provider = None
    mock_patient = MagicMock()
    mock_patient.first_name = "Bob"
    mock_patient.last_name = "Jones"
    with (
        patch("visit_summaries.protocols.summary_api.Note") as MockNote,
        patch("visit_summaries.protocols.summary_api.Patient") as MockPatient,
        patch("visit_summaries.protocols.summary_api.build_note_context_for_llm", return_value="ctx"),
        patch("visit_summaries.protocols.summary_api.generate_avs", return_value="<div>Hi</div>"),
    ):
        MockNote.objects.select_related.return_value.filter.return_value.first.return_value = mock_note
        MockPatient.objects.filter.return_value.first.return_value = mock_patient
        result = api.generate_avs_endpoint()
    assert b"avs_subtitle" in result[0].content
    assert b"for Bob Jones on Mar 1, 2025" in result[0].content
