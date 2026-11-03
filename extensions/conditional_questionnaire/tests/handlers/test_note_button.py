from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

from canvas_sdk.effects.launch_modal import LaunchModalEffect

from conditional_questionnaire.handlers.note_button import ConditionalQuestionnaireButton

MODULE = "conditional_questionnaire.handlers.note_button"


def _button(context):
    button = ConditionalQuestionnaireButton.__new__(ConditionalQuestionnaireButton)
    button.event = MagicMock()
    button.event.context = context
    return button


def test_visible_only_on_a_note():
    assert _button({}).visible() is False


def test_visible_on_an_editable_note():
    with patch(f"{MODULE}.CurrentNoteStateEvent") as states:
        states.objects.filter.return_value.first.return_value.editable.return_value = True
        assert _button({"note_id": 7}).visible() is True
    states.objects.filter.assert_called_once_with(note_id=7)


def test_hidden_on_a_locked_note():
    with patch(f"{MODULE}.CurrentNoteStateEvent") as states:
        states.objects.filter.return_value.first.return_value.editable.return_value = False
        assert _button({"note_id": 7}).visible() is False


def test_visible_when_the_note_has_no_state_row():
    with patch(f"{MODULE}.CurrentNoteStateEvent") as states:
        states.objects.filter.return_value.first.return_value = None
        assert _button({"note_id": 7}).visible() is True


def test_handle_without_note():
    assert _button({}).handle() == []


def test_handle_unknown_note():
    with patch(f"{MODULE}.Note") as note:
        note.objects.filter.return_value.values_list.return_value.first.return_value = None
        assert _button({"note_id": 7}).handle() == []
    note.objects.filter.assert_called_once_with(dbid=7)


def test_handle_opens_the_form_in_the_right_pane():
    note_uuid = "5b0b4a1e-9a43-4d39-8f3c-1f7f9b0c2d11"
    with patch(f"{MODULE}.Note") as note, patch.object(LaunchModalEffect, "apply") as apply:
        note.objects.filter.return_value.values_list.return_value.first.return_value = note_uuid
        apply.return_value = "effect"
        effects = _button({"note_id": 7}).handle()
    assert effects == ["effect"]


def test_launch_url_and_target():
    note_uuid = "5b0b4a1e-9a43-4d39-8f3c-1f7f9b0c2d11"
    with patch(f"{MODULE}.Note") as note, patch(f"{MODULE}.LaunchModalEffect") as modal:
        note.objects.filter.return_value.values_list.return_value.first.return_value = note_uuid
        _button({"note_id": 7}).handle()
    kwargs = modal.call_args.kwargs
    url = urlparse(kwargs["url"])
    assert url.path == "/plugin-io/api/conditional_questionnaire/form"
    assert parse_qs(url.query)["note_id"] == [note_uuid]
    assert kwargs["target"] == modal.TargetType.RIGHT_CHART_PANE
