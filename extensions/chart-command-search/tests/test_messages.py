from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

from chart_command_search.searchers.messages import search_messages


def _mock_obj(**kwargs: Any) -> MagicMock:
    obj = MagicMock()
    for k, v in kwargs.items():
        setattr(obj, k, v)
    return obj


def _make_message(**overrides: Any) -> MagicMock:
    note = _mock_obj(
        dbid=1,
        provider=_mock_obj(first_name="Dr", last_name="Smith"),
    )
    defaults: dict[str, Any] = {
        "content": "Hello, how are you feeling today?",
        "sender": _mock_obj(first_name="Dr", last_name="Smith", is_staff=True),
        "recipient": _mock_obj(first_name="John", last_name="Patient"),
        "note": note,
        "read": None,
        "created": datetime(2024, 3, 1, 10, 0),
    }
    defaults.update(overrides)
    return _mock_obj(**defaults)


def _setup_msg_qs(mock_msg_cls: Any, messages: list[Any]) -> None:
    qs = mock_msg_cls.objects.filter.return_value
    qs.filter.return_value = qs
    qs.select_related.return_value = qs
    qs.order_by.return_value.__getitem__ = lambda self, s: messages


@patch("chart_command_search.searchers.messages.Message")
class TestSearchMessages:
    def test_outbound_message(self, mock_msg: Any) -> None:
        msg = _make_message()
        _setup_msg_qs(mock_msg, [msg])

        results = search_messages("patient-1", "", "")
        assert len(results) == 1
        assert results[0]["category"] == "message"
        assert results[0]["type_label"] == "From Dr Smith"
        assert results[0]["state"] == ""

    def test_inbound_unread(self, mock_msg: Any) -> None:
        msg = _make_message(
            sender=_mock_obj(first_name="John", last_name="Patient", is_staff=False),
            read=None,
        )
        _setup_msg_qs(mock_msg, [msg])

        results = search_messages("patient-1", "", "")
        assert results[0]["state"] == "Unread"
        assert results[0]["state_class"] == "pending"

    def test_inbound_read(self, mock_msg: Any) -> None:
        msg = _make_message(
            sender=_mock_obj(first_name="John", last_name="Patient", is_staff=False),
            read=datetime(2024, 3, 1, 11, 0),
        )
        _setup_msg_qs(mock_msg, [msg])

        results = search_messages("patient-1", "", "")
        assert results[0]["state"] == "Read"
        assert results[0]["state_class"] == "completed"

    def test_from_patient_label(self, mock_msg: Any) -> None:
        msg = _make_message(
            sender=_mock_obj(first_name="", last_name="", is_staff=False),
            recipient=None,
            note=_mock_obj(dbid=1, provider=None),
        )
        _setup_msg_qs(mock_msg, [msg])

        results = search_messages("patient-1", "", "")
        assert results[0]["type_label"] == "From patient"

    def test_to_recipient_label(self, mock_msg: Any) -> None:
        msg = _make_message(
            sender=_mock_obj(first_name="", last_name="", is_staff=False),
            recipient=_mock_obj(first_name="Dr", last_name="Jones"),
            note=_mock_obj(dbid=1, provider=None),
        )
        _setup_msg_qs(mock_msg, [msg])

        results = search_messages("patient-1", "", "")
        assert results[0]["type_label"] == "To Dr Jones"

    def test_empty_results(self, mock_msg: Any) -> None:
        _setup_msg_qs(mock_msg, [])
        results = search_messages("patient-1", "", "")
        assert results == []

    def test_html_content_stripped(self, mock_msg: Any) -> None:
        msg = _make_message(content="<p>Hello <b>world</b></p>")
        _setup_msg_qs(mock_msg, [msg])

        results = search_messages("patient-1", "", "")
        assert results[0]["summary"] == "Hello world"

    def test_long_content_truncated(self, mock_msg: Any) -> None:
        msg = _make_message(content="x" * 300)
        _setup_msg_qs(mock_msg, [msg])

        results = search_messages("patient-1", "", "")
        assert results[0]["summary"].endswith("...")
        assert len(results[0]["summary"]) <= 204

    def test_text_query(self, mock_msg: Any) -> None:
        msg = _make_message()
        _setup_msg_qs(mock_msg, [msg])

        results = search_messages("patient-1", "feeling", "")
        assert len(results) == 1

    def test_date_filter(self, mock_msg: Any) -> None:
        msg = _make_message()
        _setup_msg_qs(mock_msg, [msg])

        results = search_messages("patient-1", "", "", date_from="2024-01-01", date_to="2024-12-31")
        assert len(results) == 1

    def test_provider_filter(self, mock_msg: Any) -> None:
        msg = _make_message()
        _setup_msg_qs(mock_msg, [msg])

        results = search_messages("patient-1", "", "", provider_id="prov-1")
        assert len(results) == 1

    def test_status_filter(self, mock_msg: Any) -> None:
        msg = _make_message()
        _setup_msg_qs(mock_msg, [msg])

        results = search_messages("patient-1", "", "read")
        assert len(results) == 1

    def test_select_related_fallback(self, mock_msg: Any) -> None:
        msg = _make_message()
        qs = mock_msg.objects.filter.return_value
        qs.filter.return_value = qs

        call_count = 0

        def side_effect(*args: Any, **kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("recipient relation not available")
            result = MagicMock()
            result.order_by.return_value.__getitem__ = lambda self, s: [msg]
            return result

        qs.select_related.side_effect = side_effect

        results = search_messages("patient-1", "", "")
        assert len(results) == 1

    def test_no_note_no_permalink(self, mock_msg: Any) -> None:
        msg = _make_message(note=None)
        _setup_msg_qs(mock_msg, [msg])

        results = search_messages("patient-1", "", "")
        assert results[0]["permalink"] == ""

    def test_outbound_fallback_to_provider_name(self, mock_msg: Any) -> None:
        msg = _make_message(
            sender=_mock_obj(first_name="", last_name="", is_staff=True),
            note=_mock_obj(dbid=1, provider=_mock_obj(first_name="Dr", last_name="Provider")),
        )
        _setup_msg_qs(mock_msg, [msg])

        results = search_messages("patient-1", "", "")
        assert results[0]["type_label"] == "From Dr Provider"

    def test_outbound_fallback_to_staff(self, mock_msg: Any) -> None:
        msg = _make_message(
            sender=_mock_obj(first_name="", last_name="", is_staff=True),
            note=_mock_obj(dbid=1, provider=None),
        )
        _setup_msg_qs(mock_msg, [msg])

        results = search_messages("patient-1", "", "")
        assert results[0]["type_label"] == "From Staff"
