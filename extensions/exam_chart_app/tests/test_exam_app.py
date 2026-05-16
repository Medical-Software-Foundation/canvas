"""Unit tests for the note-type-filter helper used by ExamChartingApp.visible()."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from exam_chart_app.applications.exam_app import (
    EXAM_NOTE_TYPES_SECRET,
    ExamChartingApp,
    _validate_icd10_search_url,
    is_exam_note,
)


@pytest.fixture
def fake_note() -> MagicMock:
    note = MagicMock()
    note.note_type_version.name = "Office Visit"
    return note


@patch("exam_chart_app.applications.exam_app.Note")
def test_empty_secret_means_visible_everywhere(mock_note_cls, fake_note):
    mock_note_cls.objects.select_related.return_value.get.return_value = fake_note
    assert is_exam_note(note_dbid=42, secret_value=None) is True
    assert is_exam_note(note_dbid=42, secret_value="") is True
    assert is_exam_note(note_dbid=42, secret_value="   ") is True


@patch("exam_chart_app.applications.exam_app.Note")
def test_matching_keyword_returns_true(mock_note_cls, fake_note):
    mock_note_cls.objects.select_related.return_value.get.return_value = fake_note
    assert is_exam_note(note_dbid=42, secret_value="Office Visit") is True
    assert is_exam_note(note_dbid=42, secret_value="office") is True
    assert is_exam_note(note_dbid=42, secret_value="telehealth, office visit") is True


@patch("exam_chart_app.applications.exam_app.Note")
def test_non_matching_keyword_returns_false(mock_note_cls, fake_note):
    mock_note_cls.objects.select_related.return_value.get.return_value = fake_note
    assert is_exam_note(note_dbid=42, secret_value="telehealth") is False


@patch("exam_chart_app.applications.exam_app.Note")
def test_missing_note_dbid_with_filter_set_returns_false(mock_note_cls):
    assert is_exam_note(note_dbid=None, secret_value="office") is False
    assert is_exam_note(note_dbid="", secret_value="office") is False
    mock_note_cls.objects.select_related.assert_not_called()


@patch("exam_chart_app.applications.exam_app.Note")
def test_missing_note_dbid_returns_false_even_with_filter_unset(mock_note_cls):
    """No note context -> False, even when the keyword secret is unset.

    Canvas evaluates `visible()` for the global application-drawer too;
    returning True there caused the Exam tab to surface as a top-level
    app icon, which is wrong for a NoteApplication. Bail out when
    note_id is absent."""
    assert is_exam_note(note_dbid=None, secret_value="") is False
    assert is_exam_note(note_dbid=None, secret_value=None) is False
    assert is_exam_note(note_dbid="", secret_value="") is False
    mock_note_cls.objects.select_related.assert_not_called()


@patch("exam_chart_app.applications.exam_app.Note")
def test_note_not_found_returns_false(mock_note_cls):
    from canvas_sdk.v1.data.note import Note as _RealNote
    mock_note_cls.objects.select_related.return_value.get.side_effect = _RealNote.DoesNotExist
    mock_note_cls.DoesNotExist = _RealNote.DoesNotExist
    assert is_exam_note(note_dbid=42, secret_value="office") is False


# --- ExamChartingApp.visible() / handle() ---------------------------------


def _make_app(
    note_id: str | int | None = None,
    patient_id: str = "",
    target_id: str = "",
    secrets: dict | None = None,
) -> ExamChartingApp:
    app = ExamChartingApp.__new__(ExamChartingApp)
    event = MagicMock()
    event.context = {"note_id": note_id, "patient_id": patient_id}
    event.target.id = target_id
    app.event = event
    app.secrets = secrets or {}
    return app


@patch("exam_chart_app.applications.exam_app.is_exam_note")
def test_visible_delegates_to_is_exam_note(mock_is_exam):
    mock_is_exam.return_value = True
    app = _make_app(note_id=42, secrets={EXAM_NOTE_TYPES_SECRET: "office"})
    assert app.visible() is True
    mock_is_exam.assert_called_once_with(42, "office")


@patch("exam_chart_app.applications.exam_app.LaunchModalEffect")
@patch("exam_chart_app.applications.exam_app.render_to_string")
@patch("exam_chart_app.applications.exam_app.Note")
def test_handle_renders_exam_html_with_resolved_note_uuid(
    mock_note_cls, mock_render, mock_modal,
):
    fake_note = MagicMock()
    fake_note.id = "11111111-1111-1111-1111-111111111111"
    fake_note.note_type_version.name = "Office Visit"
    mock_note_cls.objects.select_related.return_value.get.return_value = fake_note
    mock_render.return_value = "<html/>"
    mock_modal.return_value.apply.return_value = "MODAL_EFFECT"
    mock_modal.TargetType.NOTE = "NOTE_TARGET"

    app = _make_app(note_id=42, patient_id="pat-1")
    result = app.handle()

    assert result == ["MODAL_EFFECT"]
    mock_render.assert_called_once()
    template_name, ctx = mock_render.call_args.args
    assert template_name == "templates/exam.html"
    assert ctx["note_uuid"] == "11111111-1111-1111-1111-111111111111"
    assert ctx["patient_id"] == "pat-1"
    assert ctx["note_type_name"] == "Office Visit"
    assert ctx["api_base"] == "/plugin-io/api/exam_chart_app"
    assert ctx["exam_config"] == {
        "note_uuid": "11111111-1111-1111-1111-111111111111",
        "patient_id": "pat-1",
        "api_base": "/plugin-io/api/exam_chart_app",
    }
    mock_modal.assert_called_once_with(
        target="NOTE_TARGET", content="<html/>", title="Exam",
    )


@patch("exam_chart_app.applications.exam_app.LaunchModalEffect")
@patch("exam_chart_app.applications.exam_app.render_to_string")
@patch("exam_chart_app.applications.exam_app.Note")
def test_handle_falls_back_to_target_id_when_no_patient_id_in_context(
    mock_note_cls, mock_render, mock_modal,
):
    fake_note = MagicMock()
    fake_note.id = "uuid-x"
    fake_note.note_type_version.name = ""
    mock_note_cls.objects.select_related.return_value.get.return_value = fake_note
    mock_render.return_value = "<html/>"
    mock_modal.return_value.apply.return_value = "MODAL_EFFECT"
    mock_modal.TargetType.NOTE = "NOTE_TARGET"

    app = _make_app(note_id=42, patient_id="", target_id="pat-from-target")
    app.handle()

    ctx = mock_render.call_args.args[1]
    assert ctx["patient_id"] == "pat-from-target"


@patch("exam_chart_app.applications.exam_app.LaunchModalEffect")
@patch("exam_chart_app.applications.exam_app.render_to_string")
@patch("exam_chart_app.applications.exam_app.Note")
def test_handle_renders_empty_note_uuid_when_note_missing(
    mock_note_cls, mock_render, mock_modal,
):
    from canvas_sdk.v1.data.note import Note as _RealNote
    mock_note_cls.DoesNotExist = _RealNote.DoesNotExist
    mock_note_cls.objects.select_related.return_value.get.side_effect = (
        _RealNote.DoesNotExist
    )
    mock_render.return_value = "<html/>"
    mock_modal.return_value.apply.return_value = "MODAL_EFFECT"
    mock_modal.TargetType.NOTE = "NOTE_TARGET"

    app = _make_app(note_id=42, patient_id="pat-1")
    app.handle()

    ctx = mock_render.call_args.args[1]
    assert ctx["note_uuid"] == ""
    assert ctx["note_type_name"] == ""


@patch("exam_chart_app.applications.exam_app.LaunchModalEffect")
@patch("exam_chart_app.applications.exam_app.render_to_string")
@patch("exam_chart_app.applications.exam_app.Note")
def test_handle_skips_note_lookup_when_note_id_absent(
    mock_note_cls, mock_render, mock_modal,
):
    mock_render.return_value = "<html/>"
    mock_modal.return_value.apply.return_value = "MODAL_EFFECT"
    mock_modal.TargetType.NOTE = "NOTE_TARGET"

    app = _make_app(note_id=None, patient_id="pat-1")
    app.handle()

    mock_note_cls.objects.select_related.assert_not_called()
    ctx = mock_render.call_args.args[1]
    assert ctx["note_uuid"] == ""


@patch("exam_chart_app.applications.exam_app.LaunchModalEffect")
@patch("exam_chart_app.applications.exam_app.render_to_string")
@patch("exam_chart_app.applications.exam_app.Note")
def test_handle_passes_icd10_search_url_when_secret_set(
    mock_note_cls, mock_render, mock_modal,
):
    """The `icd10-search-url` secret should flow into exam_config so the
    JS bundle's `CONFIG.icd10_search_url || default` override fires."""
    fake_note = MagicMock()
    fake_note.id = "uuid-x"
    fake_note.note_type_version.name = ""
    mock_note_cls.objects.select_related.return_value.get.return_value = fake_note
    mock_render.return_value = "<html/>"
    mock_modal.return_value.apply.return_value = "MODAL_EFFECT"
    mock_modal.TargetType.NOTE = "NOTE_TARGET"

    app = _make_app(
        note_id=42, patient_id="pat-1",
        secrets={"icd10-search-url": "https://icd.internal.example.com/search"},
    )
    app.handle()

    ctx = mock_render.call_args.args[1]
    assert ctx["exam_config"]["icd10_search_url"] == "https://icd.internal.example.com/search"


@patch("exam_chart_app.applications.exam_app.LaunchModalEffect")
@patch("exam_chart_app.applications.exam_app.render_to_string")
@patch("exam_chart_app.applications.exam_app.Note")
def test_handle_omits_icd10_search_url_when_secret_unset(
    mock_note_cls, mock_render, mock_modal,
):
    """When unset, the key should NOT appear in exam_config — that lets the
    JS-side `|| default` fallback fire instead of seeing an empty string."""
    fake_note = MagicMock()
    fake_note.id = "uuid-x"
    fake_note.note_type_version.name = ""
    mock_note_cls.objects.select_related.return_value.get.return_value = fake_note
    mock_render.return_value = "<html/>"
    mock_modal.return_value.apply.return_value = "MODAL_EFFECT"
    mock_modal.TargetType.NOTE = "NOTE_TARGET"

    app = _make_app(note_id=42, patient_id="pat-1", secrets={})
    app.handle()

    ctx = mock_render.call_args.args[1]
    assert "icd10_search_url" not in ctx["exam_config"]


# ----- _validate_icd10_search_url -----


@pytest.mark.parametrize("value", [
    "https://clinicaltables.nlm.nih.gov/api/icd10cm/v3/search",
    "https://icd.internal.example.com/search",
    "https://icd-mirror.example.org/v3/search?cohort=primary",
    "  https://example.com  ",  # leading/trailing whitespace is stripped
])
def test_validate_icd10_search_url_accepts_https_public_hosts(value):
    assert _validate_icd10_search_url(value) == value.strip()


@pytest.mark.parametrize("value", [
    "",
    "   ",
    None,
    "not a url",
    "http://example.com",  # http, not https
    "ftp://example.com/file",
    "file:///etc/passwd",
    "javascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "https://localhost/search",
    "https://localhost:8080/search",
    "https://127.0.0.1/search",
    "https://0.0.0.0/search",
    "https://[::1]/search",
    "https://10.0.0.5/search",
    "https://10.20.30.40/path",
    "https://192.168.1.1/",
    "https://172.16.0.1/",
    "https://172.31.255.254/",
    "https://169.254.169.254/latest/meta-data/",  # AWS IMDS
    "https:///no-host",
])
def test_validate_icd10_search_url_rejects_unsafe_values(value):
    assert _validate_icd10_search_url(value) == ""


def test_validate_icd10_search_url_accepts_172_outside_private_range():
    """172.0.0.0/8 minus 172.16.0.0/12 is public IP space — should be
    accepted. (We aren't trying to encyclopedically block public IPs;
    only RFC-1918 private and loopback ranges.)"""
    assert _validate_icd10_search_url("https://172.15.0.1/") == "https://172.15.0.1/"
    assert _validate_icd10_search_url("https://172.32.0.1/") == "https://172.32.0.1/"


@patch("exam_chart_app.applications.exam_app.LaunchModalEffect")
@patch("exam_chart_app.applications.exam_app.render_to_string")
@patch("exam_chart_app.applications.exam_app.Note")
def test_handle_drops_unsafe_icd10_search_url(
    mock_note_cls, mock_render, mock_modal,
):
    """An operator-set secret that fails validation must not leak into
    exam_config — the JS-side default fires instead. A warning is logged
    so the operator notices the misconfiguration."""
    fake_note = MagicMock()
    fake_note.id = "uuid-x"
    fake_note.note_type_version.name = ""
    mock_note_cls.objects.select_related.return_value.get.return_value = fake_note
    mock_render.return_value = "<html/>"
    mock_modal.return_value.apply.return_value = "MODAL_EFFECT"
    mock_modal.TargetType.NOTE = "NOTE_TARGET"

    app = _make_app(
        note_id=42, patient_id="pat-1",
        secrets={"icd10-search-url": "http://internal-staging:8080/icd"},
    )
    app.handle()

    ctx = mock_render.call_args.args[1]
    assert "icd10_search_url" not in ctx["exam_config"]
