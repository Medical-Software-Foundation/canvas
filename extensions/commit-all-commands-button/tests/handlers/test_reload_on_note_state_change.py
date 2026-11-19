from unittest.mock import Mock, patch

from canvas_sdk.events import EventType

from commit_all_commands_button.handlers.reload_on_note_state_change import (
    ReloadButtonsOnNoteStateChange,
)

MODULE = "commit_all_commands_button.handlers.reload_on_note_state_change"
NOTE_UUID = "5623b844-aa6c-4422-9227-2b3488455393"


def make_handler(context: dict) -> ReloadButtonsOnNoteStateChange:
    event = Mock()
    event.context = context
    return ReloadButtonsOnNoteStateChange(event=event)


def test_responds_to_note_state_change_created():
    assert ReloadButtonsOnNoteStateChange.RESPONDS_TO == EventType.Name(
        EventType.NOTE_STATE_CHANGE_EVENT_CREATED
    )


@patch(f"{MODULE}.ReloadNoteActionButtonsEffect")
def test_reloads_buttons_for_the_note(mock_reload):
    mock_reload.return_value.apply.return_value = "reload-effect"

    effects = make_handler({"note_id": NOTE_UUID, "state": "ULK"}).compute()

    mock_reload.assert_called_once_with(id=NOTE_UUID)
    assert effects == ["reload-effect"]


@patch(f"{MODULE}.log")
@patch(f"{MODULE}.ReloadNoteActionButtonsEffect")
def test_no_reload_without_note_id(mock_reload, mock_log):
    assert make_handler({"note_id": None, "state": "LKD"}).compute() == []
    mock_reload.assert_not_called()
    mock_log.warning.assert_called_once()
