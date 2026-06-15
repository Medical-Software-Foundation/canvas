import json
from unittest.mock import MagicMock, patch

from questionnaire_scoring_dashboard.api.routes import (
    ScoringDashboardAPI,
    _format_change,
)


def test_format_change_branches():
    assert _format_change(None) == "-"
    assert _format_change(3.0) == "+3.0"
    assert _format_change(-2.0) == "-2.0"
    assert _format_change(0.0) == "0.0"


def _api(query=None, body=None):
    api = ScoringDashboardAPI.__new__(ScoringDashboardAPI)
    api.request = MagicMock()
    api.request.query_params = query or {}
    if body is not None:
        api.request.json.return_value = body
    return api


def _content_str(response):
    c = response.content
    return c if isinstance(c, str) else c.decode()


@patch("questionnaire_scoring_dashboard.api.routes.fetch_survey_rows")
@patch("questionnaire_scoring_dashboard.api.routes.render_to_string")
def test_index_returns_html(mock_render, mock_fetch):
    mock_render.return_value = "<html>ok</html>"
    mock_fetch.return_value = []
    api = _api(query={"patient": "p1"})
    out = api.index()
    assert out[0].status_code == 200


@patch("questionnaire_scoring_dashboard.api.routes.fetch_survey_rows")
def test_data_returns_series_and_metrics_json(mock_fetch):
    mock_fetch.return_value = [
        {"name": "PHQ-9", "value": "20", "effective_datetime": "2026-01-01T00:00:00+00:00", "created": None, "note_id": None},
        {"name": "PHQ-9", "value": "16", "effective_datetime": "2026-01-20T00:00:00+00:00", "created": None, "note_id": None},
    ]
    api = _api(query={"patient": "p1", "start": "", "end": ""})
    out = api.data()
    payload = json.loads(_content_str(out[0]))
    assert "PHQ-9" in payload
    assert payload["PHQ-9"]["metrics"]["latest"] == 16.0
    assert payload["PHQ-9"]["metrics"]["total"] == 2
    assert payload["PHQ-9"]["max_score"] == 27


def test_style_returns_css():
    with patch("questionnaire_scoring_dashboard.api.routes.render_to_string", return_value="body{}"):
        out = _api().get_css()
        assert out[0].headers.get("Content-Type") == "text/css"


@patch("questionnaire_scoring_dashboard.api.routes.fetch_open_note_rows")
def test_notes_returns_sorted_with_default(mock_fetch):
    mock_fetch.return_value = [
        {"id": "a", "dos": "2026-01-30T10:00:00+00:00", "title": "Telehealth"},
        {"id": "b", "dos": "2026-02-14T09:00:00+00:00", "title": "Office Visit"},
    ]
    api = _api(query={"patient": "p1"})
    out = api.notes()
    payload = json.loads(_content_str(out[0]))
    assert payload[0]["id"] == "b" and payload[0]["default"] is True


@patch("questionnaire_scoring_dashboard.api.routes.fetch_open_note_rows")
@patch("questionnaire_scoring_dashboard.api.routes.ScoringTrendCommand")
@patch("questionnaire_scoring_dashboard.api.routes.render_to_string")
@patch("questionnaire_scoring_dashboard.api.routes.fetch_survey_rows")
def test_insert_originates_command_into_note(mock_fetch, mock_render, mock_cmd, mock_notes):
    mock_fetch.return_value = [
        {"name": "PHQ-9", "value": "20", "effective_datetime": "2026-01-01T00:00:00+00:00", "created": None, "note_id": None},
        {"name": "PHQ-9", "value": "16", "effective_datetime": "2026-01-20T00:00:00+00:00", "created": None, "note_id": None},
    ]
    mock_render.return_value = "<html/>"
    mock_notes.return_value = [{"id": "rk786p", "dos": "2026-02-01T00:00:00+00:00", "title": "Visit"}]
    instance = mock_cmd.return_value
    instance.originate.return_value = "EFFECT"
    api = _api(body={"patient": "p1", "instrument": "PHQ-9", "start": "", "end": "", "note_uuid": "rk786p"})
    out = api.insert()
    assert "EFFECT" in out
    assert instance.note_uuid == "rk786p"
    assert instance.command_uuid


def test_insert_rejects_missing_note_uuid():
    api = _api(body={"patient": "p1", "instrument": "PHQ-9", "note_uuid": ""})
    out = api.insert()
    assert out[0].status_code == 400


@patch("questionnaire_scoring_dashboard.api.routes.fetch_open_note_rows")
def test_insert_rejects_note_from_other_patient(mock_notes):
    mock_notes.return_value = [{"id": "valid-note", "dos": "2026-02-01T00:00:00+00:00", "title": "Visit"}]
    api = _api(body={"patient": "p1", "instrument": "PHQ-9", "note_uuid": "someone-elses-note"})
    out = api.insert()
    assert out[0].status_code == 403


_TWO_INSTRUMENT_ROWS = [
    {"name": "PHQ-9", "value": "20", "effective_datetime": "2026-01-01T00:00:00+00:00", "created": None, "note_id": None},
    {"name": "PHQ-9", "value": "16", "effective_datetime": "2026-01-20T00:00:00+00:00", "created": None, "note_id": None},
    {"name": "GAD-7", "value": "15", "effective_datetime": "2026-01-01T00:00:00+00:00", "created": None, "note_id": None},
    {"name": "GAD-7", "value": "9", "effective_datetime": "2026-01-20T00:00:00+00:00", "created": None, "note_id": None},
]


@patch("questionnaire_scoring_dashboard.api.routes.fetch_open_note_rows")
@patch("questionnaire_scoring_dashboard.api.routes.ScoringTrendCommand")
@patch("questionnaire_scoring_dashboard.api.routes.render_to_string")
@patch("questionnaire_scoring_dashboard.api.routes.fetch_survey_rows")
def test_insert_compare_builds_one_row_per_instrument(mock_fetch, mock_render, mock_cmd, mock_notes):
    mock_fetch.return_value = _TWO_INSTRUMENT_ROWS
    mock_render.return_value = "<html/>"
    mock_notes.return_value = [{"id": "n1", "dos": "2026-02-01T00:00:00+00:00", "title": "Visit"}]
    instance = mock_cmd.return_value
    instance.originate.return_value = "EFFECT"
    api = _api(body={"patient": "p1", "instruments": ["PHQ-9", "GAD-7"], "start": "", "end": "", "note_uuid": "n1"})
    out = api.insert_compare()

    assert "EFFECT" in out and instance.note_uuid == "n1"
    # The compare template gets a row per instrument with distinct colors and
    # the computed latest score / change.
    ctx = mock_render.call_args_list[0].kwargs["context"]
    assert ctx["count"] == 2
    rows = {r["name"]: r for r in ctx["rows"]}
    assert rows["PHQ-9"]["latest"] == 16.0 and rows["PHQ-9"]["change"] == "-4.0"
    assert rows["GAD-7"]["latest"] == 9.0 and rows["GAD-7"]["change"] == "-6.0"
    assert rows["PHQ-9"]["color"] != rows["GAD-7"]["color"]
    assert mock_render.call_args_list[0].args[0] == "templates/command_compare.html"


@patch("questionnaire_scoring_dashboard.api.routes.fetch_open_note_rows")
@patch("questionnaire_scoring_dashboard.api.routes.ScoringTrendCommand")
@patch("questionnaire_scoring_dashboard.api.routes.render_to_string")
@patch("questionnaire_scoring_dashboard.api.routes.fetch_survey_rows")
def test_insert_compare_skips_instruments_without_data(mock_fetch, mock_render, mock_cmd, mock_notes):
    mock_fetch.return_value = _TWO_INSTRUMENT_ROWS  # PHQ-9 + GAD-7 only
    mock_render.return_value = "<html/>"
    mock_notes.return_value = [{"id": "n1", "dos": "2026-02-01T00:00:00+00:00", "title": "Visit"}]
    api = _api(body={"patient": "p1", "instruments": ["PHQ-9", "AUDIT"], "start": "", "end": "", "note_uuid": "n1"})
    api.insert_compare()
    ctx = mock_render.call_args_list[0].kwargs["context"]
    assert ctx["count"] == 1
    assert [r["name"] for r in ctx["rows"]] == ["PHQ-9"]


@patch("questionnaire_scoring_dashboard.api.routes.fetch_open_note_rows")
@patch("questionnaire_scoring_dashboard.api.routes.ScoringTrendCommand")
@patch("questionnaire_scoring_dashboard.api.routes.render_to_string")
@patch("questionnaire_scoring_dashboard.api.routes.fetch_survey_rows")
def test_insert_compare_no_data_uses_no_data_range(mock_fetch, mock_render, mock_cmd, mock_notes):
    mock_fetch.return_value = _TWO_INSTRUMENT_ROWS  # no AUDIT data
    mock_render.return_value = "<html/>"
    mock_notes.return_value = [{"id": "n1", "dos": "2026-02-01T00:00:00+00:00", "title": "Visit"}]
    api = _api(body={"patient": "p1", "instruments": ["AUDIT"], "start": "", "end": "", "note_uuid": "n1"})
    api.insert_compare()
    ctx = mock_render.call_args_list[0].kwargs["context"]
    assert ctx["count"] == 0 and ctx["date_range"] == "No data"


def test_insert_compare_rejects_missing_instruments():
    api = _api(body={"patient": "p1", "instruments": [], "note_uuid": "n1"})
    out = api.insert_compare()
    assert out[0].status_code == 400


@patch("questionnaire_scoring_dashboard.api.routes.fetch_open_note_rows")
def test_insert_compare_rejects_note_from_other_patient(mock_notes):
    mock_notes.return_value = [{"id": "valid-note", "dos": "2026-02-01T00:00:00+00:00", "title": "Visit"}]
    api = _api(body={"patient": "p1", "instruments": ["PHQ-9"], "note_uuid": "someone-elses-note"})
    out = api.insert_compare()
    assert out[0].status_code == 403
