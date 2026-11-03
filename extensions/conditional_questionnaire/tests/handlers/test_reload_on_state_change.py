from unittest.mock import MagicMock, patch

from conditional_questionnaire.handlers.reload_on_state_change import (
    ReloadButtonOnNoteStateChange,
)

MODULE = "conditional_questionnaire.handlers.reload_on_state_change"


def _handler(context):
    handler = ReloadButtonOnNoteStateChange.__new__(ReloadButtonOnNoteStateChange)
    handler.event = MagicMock()
    handler.event.context = context
    return handler


def test_reloads_the_notes_buttons_on_a_state_change():
    note_uuid = "5b0b4a1e-9a43-4d39-8f3c-1f7f9b0c2d11"
    with patch(f"{MODULE}.ReloadNoteActionButtonsEffect") as reload:
        reload.return_value.apply.return_value = "effect"
        effects = _handler({"note_id": note_uuid, "state": "LKD"}).compute()
    assert effects == ["effect"]
    reload.assert_called_once_with(id=note_uuid)


def test_no_note_id_does_nothing():
    with patch(f"{MODULE}.ReloadNoteActionButtonsEffect") as reload:
        assert _handler({}).compute() == []
    reload.assert_not_called()
