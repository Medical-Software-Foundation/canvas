"""Tests for what POST /cosign/<note_id>/ hands back to Canvas."""

from unittest.mock import MagicMock, patch

from canvas_sdk.effects.simple_api import JSONResponse

from supervisor_cosign.api.handlers import SupervisorCoSignAPI

MODULE = "supervisor_cosign.api.handlers"


def submit(supervisor_id: str = "supervisor", caller_id: str = "supervisor"):
    record = MagicMock()
    record.supervisor_id = supervisor_id
    record.supervisee_id = "supervisee"
    record.task_id = ""
    api = SupervisorCoSignAPI.__new__(SupervisorCoSignAPI)
    api.request = MagicMock()
    api.request.path_params = {"note_id": "note-uuid"}
    api.request.json.return_value = {"template": "reviewed", "attestation_text": "Reviewed."}
    api.request.headers = {"canvas-logged-in-user-id": caller_id}
    with (
        patch(f"{MODULE}.CoSignRecord") as record_model,
        patch(f"{MODULE}.CoSignAddendum"),
        patch(f"{MODULE}.CustomCommand") as command,
        patch(f"{MODULE}.NoteEffect") as note_effect,
        patch(f"{MODULE}.ReloadNoteActionButtonsEffect") as reload_effect,
        patch.object(SupervisorCoSignAPI, "_staff_name", return_value="Jordan Lee"),
        patch.object(SupervisorCoSignAPI, "_staff_credentialed_name", return_value="Sam Rivera, MD"),
    ):
        record_model.objects.filter.return_value = [record]
        command.return_value.originate.return_value = "originate"
        note_effect.return_value.unlock.return_value = "unlock"
        reload_effect.return_value.apply.return_value = "reload"
        result = api.submit_cosign()
    return result, record, reload_effect


def test_approval_reloads_the_note_buttons_after_the_chart_writes():
    result, record, reload_effect = submit()

    reload_effect.assert_called_once_with(id="note-uuid")
    assert record.status == "approved"
    assert result[:2] == ["unlock", "originate"]
    assert result[-2] == "reload"
    assert isinstance(result[-1], JSONResponse)


def test_rejected_caller_gets_no_reload():
    result, record, reload_effect = submit(caller_id="someone-else")

    reload_effect.assert_not_called()
    assert len(result) == 1
    record.save.assert_not_called()
