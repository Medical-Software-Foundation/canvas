"""Phase 1A tests for NutritionChartingNoteLifecycle.

Covers the four cases from the plan:
  1. State == DELETED triggers AttributeHub.filter(...).delete() with the
     plugin's namespace + the note's UUID.
  2. State != DELETED (e.g. SIGNED) is a no-op.
  3. NoteStateChangeEvent.DoesNotExist is a graceful no-op (no DB write,
     no exception bubbles up).
  4. A note that was never charted (delete() returns 0) is a graceful no-op
     — no log line, no error.
"""

from unittest.mock import MagicMock, patch

from canvas_sdk.v1.data.note import NoteStates

from nutrition_charting.data.form_state import NAMESPACE
from nutrition_charting.protocols.note_lifecycle import (
    NutritionChartingNoteLifecycle,
)


def _make_handler(state_event_id: str = "evt-1") -> NutritionChartingNoteLifecycle:
    """Build a handler instance bypassing BaseHandler's bound __init__."""
    handler = NutritionChartingNoteLifecycle.__new__(NutritionChartingNoteLifecycle)
    event = MagicMock()
    event.target.id = state_event_id
    handler.event = event
    return handler


@patch("nutrition_charting.protocols.note_lifecycle.AttributeHub")
@patch("nutrition_charting.protocols.note_lifecycle.NoteStateChangeEvent")
def test_deleted_state_removes_attribute_hub_row(
    mock_event_cls: MagicMock, mock_hub_cls: MagicMock,
) -> None:
    state_event = MagicMock()
    state_event.state = NoteStates.DELETED
    state_event.note.id = "note-uuid-1"
    mock_event_cls.objects.select_related.return_value.get.return_value = state_event
    mock_hub_cls.objects.filter.return_value.delete.return_value = (3, {"AttributeHub": 3})

    result = _make_handler().compute()

    assert result == []
    mock_event_cls.objects.select_related.assert_called_once_with("note")
    mock_event_cls.objects.select_related.return_value.get.assert_called_once_with(id="evt-1")
    mock_hub_cls.objects.filter.assert_called_once_with(type=NAMESPACE, id="note-uuid-1")
    mock_hub_cls.objects.filter.return_value.delete.assert_called_once()


@patch("nutrition_charting.protocols.note_lifecycle.AttributeHub")
@patch("nutrition_charting.protocols.note_lifecycle.NoteStateChangeEvent")
def test_non_deleted_state_is_noop(
    mock_event_cls: MagicMock, mock_hub_cls: MagicMock,
) -> None:
    state_event = MagicMock()
    state_event.state = NoteStates.SIGNED
    mock_event_cls.objects.select_related.return_value.get.return_value = state_event

    result = _make_handler().compute()

    assert result == []
    mock_hub_cls.objects.filter.assert_not_called()


@patch("nutrition_charting.protocols.note_lifecycle.AttributeHub")
@patch("nutrition_charting.protocols.note_lifecycle.NoteStateChangeEvent")
def test_missing_state_event_is_graceful_noop(
    mock_event_cls: MagicMock, mock_hub_cls: MagicMock,
) -> None:
    """Stale targets (event row purged before the handler ran) shouldn't
    crash the plugin runner."""
    class _DNE(Exception):
        pass

    mock_event_cls.DoesNotExist = _DNE
    mock_event_cls.objects.select_related.return_value.get.side_effect = _DNE()

    result = _make_handler().compute()

    assert result == []
    mock_hub_cls.objects.filter.assert_not_called()


@patch("nutrition_charting.protocols.note_lifecycle.log")
@patch("nutrition_charting.protocols.note_lifecycle.AttributeHub")
@patch("nutrition_charting.protocols.note_lifecycle.NoteStateChangeEvent")
def test_note_with_no_attribute_hub_row_is_silent_noop(
    mock_event_cls: MagicMock, mock_hub_cls: MagicMock, mock_log: MagicMock,
) -> None:
    """Notes that were never charted in the Nutrition tab have no row to
    clean up. The handler still queries (cheap), gets 0 deleted, and
    suppresses the info log to avoid noisy output for normal deletes."""
    state_event = MagicMock()
    state_event.state = NoteStates.DELETED
    state_event.note.id = "note-uuid-untouched"
    mock_event_cls.objects.select_related.return_value.get.return_value = state_event
    mock_hub_cls.objects.filter.return_value.delete.return_value = (0, {})

    result = _make_handler().compute()

    assert result == []
    mock_log.info.assert_not_called()
