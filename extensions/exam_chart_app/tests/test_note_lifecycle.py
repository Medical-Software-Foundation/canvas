"""Unit tests for ExamNoteLifecycle (Checkpoint 9)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from canvas_sdk.v1.data.note import NoteStates

from exam_chart_app.protocols.note_lifecycle import ExamNoteLifecycle


def _make_handler(state_event_id: str = "evt-1") -> ExamNoteLifecycle:
    """Build a handler bypassing BaseHandler.__init__ (which needs a real event)."""
    handler = ExamNoteLifecycle.__new__(ExamNoteLifecycle)
    event = MagicMock()
    event.target.id = state_event_id
    handler.event = event
    return handler


@patch("exam_chart_app.protocols.note_lifecycle.clear_draft")
@patch("exam_chart_app.protocols.note_lifecycle.NoteStateChangeEvent")
def test_deleted_state_clears_draft(mock_event_cls, mock_clear):
    state_event = MagicMock()
    state_event.state = NoteStates.DELETED
    state_event.note.id = "note-uuid-1"
    mock_event_cls.objects.select_related.return_value.get.return_value = state_event

    result = _make_handler().compute()

    assert result == []
    mock_event_cls.objects.select_related.assert_called_once_with("note")
    mock_event_cls.objects.select_related.return_value.get.assert_called_once_with(
        id="evt-1"
    )
    mock_clear.assert_called_once_with("note-uuid-1")


@patch("exam_chart_app.protocols.note_lifecycle.clear_draft")
@patch("exam_chart_app.protocols.note_lifecycle.NoteStateChangeEvent")
def test_non_deleted_state_is_noop(mock_event_cls, mock_clear):
    state_event = MagicMock()
    # Any state other than DELETED — pick one that providers commonly emit.
    state_event.state = NoteStates.LOCKED
    mock_event_cls.objects.select_related.return_value.get.return_value = state_event

    result = _make_handler().compute()

    assert result == []
    mock_clear.assert_not_called()


@patch("exam_chart_app.protocols.note_lifecycle.clear_draft")
@patch("exam_chart_app.protocols.note_lifecycle.NoteStateChangeEvent")
def test_missing_event_is_noop(mock_event_cls, mock_clear):
    from canvas_sdk.v1.data.note import NoteStateChangeEvent as _RealEvent
    mock_event_cls.DoesNotExist = _RealEvent.DoesNotExist
    mock_event_cls.objects.select_related.return_value.get.side_effect = (
        _RealEvent.DoesNotExist
    )

    result = _make_handler().compute()

    assert result == []
    mock_clear.assert_not_called()
