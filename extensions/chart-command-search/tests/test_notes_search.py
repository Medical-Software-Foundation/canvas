from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

from chart_command_search.searchers.notes import search_notes


def _mock_obj(**kwargs: Any) -> MagicMock:
    obj = MagicMock()
    for k, v in kwargs.items():
        setattr(obj, k, v)
    return obj


def _make_note(**overrides: Any) -> MagicMock:
    current_state = _mock_obj(state="NEW")
    current_state.editable.return_value = True
    defaults: dict[str, Any] = {
        "dbid": 1,
        "title": "Office Visit",
        "provider": _mock_obj(first_name="Jane", last_name="Doe"),
        "note_type_version": _mock_obj(display="Office Visit", name="Office Visit"),
        "current_state": current_state,
        "body": [{"type": "text", "value": "Patient presents with headache."}],
        "datetime_of_service": datetime(2024, 3, 1),
    }
    defaults.update(overrides)
    note = _mock_obj(**defaults)
    note.commands.all.return_value = []
    return note


def _setup_note_qs(mock_note_cls: Any, notes: list[Any]) -> None:
    qs = mock_note_cls.objects.filter.return_value
    qs.select_related.return_value = qs
    qs.prefetch_related.return_value = qs
    qs.filter.return_value = qs
    qs.distinct.return_value = qs
    qs.order_by.return_value.__getitem__ = lambda self, s: notes


@patch("chart_command_search.searchers.notes.Note")
class TestSearchNotes:
    def test_basic_unlocked_note(self, mock_note_cls: Any) -> None:
        note = _make_note()
        _setup_note_qs(mock_note_cls, [note])

        results = search_notes("patient-1", "", "")
        assert len(results) == 1
        assert results[0]["category"] == "note"
        assert results[0]["type_label"] == "Office Visit"
        assert results[0]["state"] == "Unlocked"
        assert results[0]["state_class"] == "unlocked"

    def test_locked_note(self, mock_note_cls: Any) -> None:
        cs = _mock_obj(state="SGN")
        cs.editable.return_value = False
        note = _make_note(current_state=cs)
        _setup_note_qs(mock_note_cls, [note])

        results = search_notes("patient-1", "", "")
        assert results[0]["state"] == "Locked"
        assert results[0]["state_class"] == "locked"

    def test_deleted_note(self, mock_note_cls: Any) -> None:
        cs = _mock_obj(state="DLT")
        cs.editable.return_value = False
        note = _make_note(current_state=cs)
        _setup_note_qs(mock_note_cls, [note])

        results = search_notes("patient-1", "", "")
        assert results[0]["state"] == "Deleted"
        assert results[0]["state_class"] == "deleted"

    def test_no_current_state(self, mock_note_cls: Any) -> None:
        note = _make_note(current_state=None)
        _setup_note_qs(mock_note_cls, [note])

        results = search_notes("patient-1", "", "")
        assert results[0]["state"] == "Unlocked"

    def test_reason_for_visit_from_commands(self, mock_note_cls: Any) -> None:
        rfv_cmd = _mock_obj(
            schema_key="reasonForVisit",
            data={"coding": {"text": "Headache follow-up"}},
        )
        note = _make_note()
        note.commands.all.return_value = [rfv_cmd]
        _setup_note_qs(mock_note_cls, [note])

        results = search_notes("patient-1", "", "")
        rfv_details = [d for d in results[0]["details"] if d["label"] == "Reason for visit"]
        assert rfv_details[0]["value"] == "Headache follow-up"

    def test_rfv_from_comment_fallback(self, mock_note_cls: Any) -> None:
        rfv_cmd = _mock_obj(
            schema_key="reasonForVisit",
            data={"comment": "Chronic pain management"},
        )
        note = _make_note()
        note.commands.all.return_value = [rfv_cmd]
        _setup_note_qs(mock_note_cls, [note])

        results = search_notes("patient-1", "", "")
        rfv_details = [d for d in results[0]["details"] if d["label"] == "Reason for visit"]
        assert rfv_details[0]["value"] == "Chronic pain management"

    def test_text_query_with_body_snippet(self, mock_note_cls: Any) -> None:
        note = _make_note(body=[{"type": "text", "value": "Patient presents with severe headache and nausea."}])
        _setup_note_qs(mock_note_cls, [note])

        results = search_notes("patient-1", "headache", "")
        assert len(results) == 1
        matched = [d for d in results[0]["details"] if d["label"] == "Matched in"]
        assert len(matched) == 1
        assert "Body" in matched[0]["value"]

    def test_status_filter_locked(self, mock_note_cls: Any) -> None:
        cs = _mock_obj(state="SGN")
        cs.editable.return_value = False
        note = _make_note(current_state=cs)
        _setup_note_qs(mock_note_cls, [note])

        results = search_notes("patient-1", "", "locked")
        assert len(results) == 1

    def test_status_filter_excludes_non_matching(self, mock_note_cls: Any) -> None:
        note = _make_note()
        _setup_note_qs(mock_note_cls, [note])

        results = search_notes("patient-1", "", "locked")
        assert len(results) == 0

    def test_note_type_status_filter(self, mock_note_cls: Any) -> None:
        note = _make_note()
        _setup_note_qs(mock_note_cls, [note])

        results = search_notes("patient-1", "", "note_type_5")
        assert len(results) == 1

    def test_date_filter(self, mock_note_cls: Any) -> None:
        note = _make_note()
        _setup_note_qs(mock_note_cls, [note])

        results = search_notes("patient-1", "", "", date_from="2024-01-01", date_to="2024-12-31")
        assert len(results) == 1

    def test_provider_filter(self, mock_note_cls: Any) -> None:
        note = _make_note()
        _setup_note_qs(mock_note_cls, [note])

        results = search_notes("patient-1", "", "", provider_id="prov-1")
        assert len(results) == 1

    def test_empty_results(self, mock_note_cls: Any) -> None:
        _setup_note_qs(mock_note_cls, [])
        results = search_notes("patient-1", "", "")
        assert results == []

    def test_long_body_truncated(self, mock_note_cls: Any) -> None:
        note = _make_note(body=[{"type": "text", "value": "x" * 300}])
        _setup_note_qs(mock_note_cls, [note])

        results = search_notes("patient-1", "", "")
        assert results[0]["summary"].endswith("...")

    def test_title_in_details_when_different_from_type(self, mock_note_cls: Any) -> None:
        note = _make_note(title="Custom Title")
        _setup_note_qs(mock_note_cls, [note])

        results = search_notes("patient-1", "", "")
        title_details = [d for d in results[0]["details"] if d["label"] == "Title"]
        assert title_details[0]["value"] == "Custom Title"

    def test_type_label_fallback_to_title(self, mock_note_cls: Any) -> None:
        note = _make_note(
            note_type_version=_mock_obj(display="", name=""),
            title="Fallback Title",
        )
        _setup_note_qs(mock_note_cls, [note])

        results = search_notes("patient-1", "", "")
        assert results[0]["type_label"] == "Fallback Title"

    def test_type_label_fallback_to_note(self, mock_note_cls: Any) -> None:
        note = _make_note(
            note_type_version=_mock_obj(display="", name=""),
            title="",
        )
        _setup_note_qs(mock_note_cls, [note])

        results = search_notes("patient-1", "", "")
        assert results[0]["type_label"] == "Note"

    def test_non_rfv_command_skipped(self, mock_note_cls: Any) -> None:
        cmd = _mock_obj(schema_key="diagnose", data={"diagnose": {"text": "HTN"}})
        note = _make_note()
        note.commands.all.return_value = [cmd]
        _setup_note_qs(mock_note_cls, [note])

        results = search_notes("patient-1", "", "")
        rfv_details = [d for d in results[0]["details"] if d["label"] == "Reason for visit"]
        assert len(rfv_details) == 0
