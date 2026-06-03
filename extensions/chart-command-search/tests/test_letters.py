from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

from chart_command_search.searchers.letters import search_letters


def _mock_obj(**kwargs: Any) -> MagicMock:
    obj = MagicMock()
    for k, v in kwargs.items():
        setattr(obj, k, v)
    return obj


def _make_note(**overrides: Any) -> MagicMock:
    defaults: dict[str, Any] = {
        "dbid": 1,
        "title": "Referral Letter",
        "provider": _mock_obj(first_name="Jane", last_name="Doe"),
        "note_type_version": _mock_obj(display="Letter", name="Letter Encounter"),
        "body": [{"type": "text", "value": "Letter body content here"}],
        "datetime_of_service": datetime(2024, 3, 1),
    }
    defaults.update(overrides)
    return _mock_obj(**defaults)


def _setup_note_qs(mock_note_cls: Any, notes: list[Any]) -> None:
    qs = mock_note_cls.objects.filter.return_value
    qs.select_related.return_value = qs
    qs.filter.return_value = qs
    qs.order_by.return_value.__getitem__ = lambda self, s: notes


@patch("chart_command_search.searchers.letters.LetterActionEvent")
@patch("chart_command_search.searchers.letters.Letter")
@patch("chart_command_search.searchers.letters.Note")
class TestSearchLetters:
    def test_basic_search(
        self, mock_note: Any, mock_letter: Any, mock_evt: Any
    ) -> None:
        note = _make_note()
        _setup_note_qs(mock_note, [note])
        letter = _mock_obj(dbid=10, note_id=1, content="Dear Dr. Smith, ...", printed=None)
        mock_letter.objects.filter.return_value.select_related.return_value = [letter]
        mock_evt.objects.filter.return_value.order_by.return_value = []

        results = search_letters("patient-1", "", "")
        assert len(results) == 1
        assert results[0]["category"] == "letter"
        assert results[0]["type_label"] == "Letter"
        assert "Dear Dr. Smith" in results[0]["summary"]

    def test_empty_results(
        self, mock_note: Any, mock_letter: Any, mock_evt: Any
    ) -> None:
        _setup_note_qs(mock_note, [])
        results = search_letters("patient-1", "", "")
        assert results == []

    def test_fax_delivered(
        self, mock_note: Any, mock_letter: Any, mock_evt: Any
    ) -> None:
        note = _make_note()
        _setup_note_qs(mock_note, [note])
        letter = _mock_obj(dbid=10, note_id=1, content="Content", printed=None)
        mock_letter.objects.filter.return_value.select_related.return_value = [letter]
        fax_evt = _mock_obj(letter_id=10, event_type="FAXED", delivered_by_fax=True)
        mock_evt.objects.filter.return_value.order_by.return_value = [fax_evt]

        results = search_letters("patient-1", "", "")
        assert results[0]["state"] == "Faxed"
        assert results[0]["state_class"] == "completed"

    def test_fax_failed(
        self, mock_note: Any, mock_letter: Any, mock_evt: Any
    ) -> None:
        note = _make_note()
        _setup_note_qs(mock_note, [note])
        letter = _mock_obj(dbid=10, note_id=1, content="Content", printed=None)
        mock_letter.objects.filter.return_value.select_related.return_value = [letter]
        fax_evt = _mock_obj(letter_id=10, event_type="FAXED", delivered_by_fax=False)
        mock_evt.objects.filter.return_value.order_by.return_value = [fax_evt]

        results = search_letters("patient-1", "", "")
        assert results[0]["state"] == "Fax failed"
        assert results[0]["state_class"] == "cancelled"

    def test_fax_pending(
        self, mock_note: Any, mock_letter: Any, mock_evt: Any
    ) -> None:
        note = _make_note()
        _setup_note_qs(mock_note, [note])
        letter = _mock_obj(dbid=10, note_id=1, content="Content", printed=None)
        mock_letter.objects.filter.return_value.select_related.return_value = [letter]
        fax_evt = _mock_obj(letter_id=10, event_type="FAXED", delivered_by_fax=None)
        mock_evt.objects.filter.return_value.order_by.return_value = [fax_evt]

        results = search_letters("patient-1", "", "")
        assert results[0]["state"] == "Fax pending"
        assert results[0]["state_class"] == "pending"

    def test_printed(
        self, mock_note: Any, mock_letter: Any, mock_evt: Any
    ) -> None:
        note = _make_note()
        _setup_note_qs(mock_note, [note])
        letter = _mock_obj(dbid=10, note_id=1, content="Content", printed=datetime(2024, 1, 1))
        mock_letter.objects.filter.return_value.select_related.return_value = [letter]
        mock_evt.objects.filter.return_value.order_by.return_value = []

        results = search_letters("patient-1", "", "")
        assert results[0]["state"] == "Printed"
        assert results[0]["state_class"] == "active"

    def test_printed_via_event(
        self, mock_note: Any, mock_letter: Any, mock_evt: Any
    ) -> None:
        note = _make_note()
        _setup_note_qs(mock_note, [note])
        letter = _mock_obj(dbid=10, note_id=1, content="Content", printed=None)
        mock_letter.objects.filter.return_value.select_related.return_value = [letter]
        print_evt = _mock_obj(letter_id=10, event_type="PRINTED")
        mock_evt.objects.filter.return_value.order_by.return_value = [print_evt]

        results = search_letters("patient-1", "", "")
        assert results[0]["state"] == "Printed"

    def test_status_filter_faxed(
        self, mock_note: Any, mock_letter: Any, mock_evt: Any
    ) -> None:
        note = _make_note()
        _setup_note_qs(mock_note, [note])
        letter = _mock_obj(dbid=10, note_id=1, content="Content", printed=None)
        mock_letter.objects.filter.return_value.select_related.return_value = [letter]
        fax_evt = _mock_obj(letter_id=10, event_type="FAXED", delivered_by_fax=True)
        mock_evt.objects.filter.return_value.order_by.return_value = [fax_evt]

        results = search_letters("patient-1", "", "faxed")
        assert len(results) == 1

    def test_status_filter_excludes_non_matching(
        self, mock_note: Any, mock_letter: Any, mock_evt: Any
    ) -> None:
        note = _make_note()
        _setup_note_qs(mock_note, [note])
        letter = _mock_obj(dbid=10, note_id=1, content="Content", printed=None)
        mock_letter.objects.filter.return_value.select_related.return_value = [letter]
        mock_evt.objects.filter.return_value.order_by.return_value = []

        results = search_letters("patient-1", "", "faxed")
        assert len(results) == 0

    def test_status_filter_fax_failed(
        self, mock_note: Any, mock_letter: Any, mock_evt: Any
    ) -> None:
        note = _make_note()
        _setup_note_qs(mock_note, [note])
        letter = _mock_obj(dbid=10, note_id=1, content="Content", printed=None)
        mock_letter.objects.filter.return_value.select_related.return_value = [letter]
        fax_evt = _mock_obj(letter_id=10, event_type="FAXED", delivered_by_fax=False)
        mock_evt.objects.filter.return_value.order_by.return_value = [fax_evt]

        results = search_letters("patient-1", "", "fax_failed")
        assert len(results) == 1

    def test_text_query_matches_title(
        self, mock_note: Any, mock_letter: Any, mock_evt: Any
    ) -> None:
        note = _make_note(title="Specialist Referral")
        _setup_note_qs(mock_note, [note])
        mock_letter.objects.filter.return_value.select_related.return_value = []
        mock_evt.objects.filter.return_value.order_by.return_value = []

        results = search_letters("patient-1", "Specialist", "")
        assert len(results) == 1
        matched = [d for d in results[0]["details"] if d["label"] == "Matched in"]
        assert matched[0]["value"] == "Title"

    def test_text_query_matches_body(
        self, mock_note: Any, mock_letter: Any, mock_evt: Any
    ) -> None:
        note = _make_note(title="Letter", body=None)
        _setup_note_qs(mock_note, [note])
        letter = _mock_obj(dbid=10, note_id=1, content="Requesting consultation for diabetes management", printed=None)
        mock_letter.objects.filter.return_value.select_related.return_value = [letter]
        mock_evt.objects.filter.return_value.order_by.return_value = []

        results = search_letters("patient-1", "diabetes", "")
        assert len(results) == 1
        matched = [d for d in results[0]["details"] if d["label"] == "Matched in"]
        assert "Body" in matched[0]["value"]

    def test_letter_encounter_type_normalized(
        self, mock_note: Any, mock_letter: Any, mock_evt: Any
    ) -> None:
        note = _make_note(
            note_type_version=_mock_obj(display="Letter Encounter", name="Letter Encounter"),
            title="",
        )
        _setup_note_qs(mock_note, [note])
        mock_letter.objects.filter.return_value.select_related.return_value = []

        results = search_letters("patient-1", "", "")
        assert results[0]["type_label"] == "Letter"

    def test_summary_from_body_when_no_letter(
        self, mock_note: Any, mock_letter: Any, mock_evt: Any
    ) -> None:
        note = _make_note(body=[{"type": "text", "value": "Body text fallback"}])
        _setup_note_qs(mock_note, [note])
        mock_letter.objects.filter.return_value.select_related.return_value = []

        results = search_letters("patient-1", "", "")
        assert "Body text fallback" in results[0]["summary"]

    def test_long_summary_truncated(
        self, mock_note: Any, mock_letter: Any, mock_evt: Any
    ) -> None:
        note = _make_note()
        _setup_note_qs(mock_note, [note])
        long_content = "x" * 300
        letter = _mock_obj(dbid=10, note_id=1, content=long_content, printed=None)
        mock_letter.objects.filter.return_value.select_related.return_value = [letter]
        mock_evt.objects.filter.return_value.order_by.return_value = []

        results = search_letters("patient-1", "", "")
        assert results[0]["summary"].endswith("...")
        assert len(results[0]["summary"]) <= 204

    def test_provider_in_details(
        self, mock_note: Any, mock_letter: Any, mock_evt: Any
    ) -> None:
        note = _make_note()
        _setup_note_qs(mock_note, [note])
        mock_letter.objects.filter.return_value.select_related.return_value = []

        results = search_letters("patient-1", "", "")
        provider_details = [d for d in results[0]["details"] if d["label"] == "Provider"]
        assert provider_details[0]["value"] == "Jane Doe"

    def test_letter_fetch_exception_handled(
        self, mock_note: Any, mock_letter: Any, mock_evt: Any
    ) -> None:
        note = _make_note()
        _setup_note_qs(mock_note, [note])
        mock_letter.objects.filter.side_effect = RuntimeError("db error")

        results = search_letters("patient-1", "", "")
        assert len(results) == 1

    def test_date_and_provider_filters(
        self, mock_note: Any, mock_letter: Any, mock_evt: Any
    ) -> None:
        note = _make_note()
        _setup_note_qs(mock_note, [note])
        mock_letter.objects.filter.return_value.select_related.return_value = []

        results = search_letters(
            "patient-1", "", "", date_from="2024-01-01", date_to="2024-12-31", provider_id="prov-1"
        )
        assert len(results) == 1

    def test_title_in_details_when_different_from_type(
        self, mock_note: Any, mock_letter: Any, mock_evt: Any
    ) -> None:
        note = _make_note(
            title="Custom Title",
            note_type_version=_mock_obj(display="Letter", name="Letter"),
        )
        _setup_note_qs(mock_note, [note])
        mock_letter.objects.filter.return_value.select_related.return_value = []

        results = search_letters("patient-1", "", "")
        title_details = [d for d in results[0]["details"] if d["label"] == "Title"]
        assert title_details[0]["value"] == "Custom Title"
