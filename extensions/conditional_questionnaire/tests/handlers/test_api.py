import json
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from conditional_questionnaire.handlers.api import ConditionalQuestionnaireAPI

MODULE = "conditional_questionnaire.handlers.api"
NOTE = "5b0b4a1e-9a43-4d39-8f3c-1f7f9b0c2d11"
QUESTIONNAIRE_ID = "0b1c2d3e-4f50-4a61-8b72-9c83d94ea5f6"
COMMAND = "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d"

QUESTIONS = [
    {
        "id": 1,
        "name": "Smoker",
        "type": "SING",
        "rule": None,
        "options": [
            {"id": 11, "name": "Yes", "code": "Y", "value": "y"},
            {"id": 12, "name": "No", "code": "N", "value": "n"},
        ],
    },
    {
        "id": 2,
        "name": "Packs",
        "type": "TXT",
        "options": [],
        "rule": {
            "behavior": "any",
            "conditions": [{"on": 1, "op": "=", "option": 11, "value": None}],
        },
    },
]
FORM = {
    "id": QUESTIONNAIRE_ID,
    "name": "Intro",
    "questions": QUESTIONS,
    "saveable": True,
    "reason": "",
}


def _api(query=None, path=None, body=None):
    api = ConditionalQuestionnaireAPI(MagicMock())
    api.request = MagicMock()
    api.request.query_params = query or {}
    api.request.path_params = path or {}
    api.request.json.return_value = body
    return api


def _json(response):
    return json.loads(response.content)


def _body(**overrides):
    body = {
        "note_id": NOTE,
        "questionnaire_id": QUESTIONNAIRE_ID,
        "command_uuid": COMMAND,
        "answers": {"1": "12", "2": "stale"},
    }
    body.update(overrides)
    return body


@pytest.fixture
def models():
    with (
        patch(f"{MODULE}.Command") as command,
        patch(f"{MODULE}.Note") as note,
        patch(f"{MODULE}.find_questionnaire") as find,
        patch(f"{MODULE}.load_form") as load,
    ):
        command.objects.filter.return_value.exists.return_value = False
        state = MagicMock()
        state.editable.return_value = True
        note.objects.filter.return_value.select_related.return_value.first.return_value = (
            SimpleNamespace(current_state=state)
        )
        find.return_value = SimpleNamespace(id=QUESTIONNAIRE_ID)
        load.return_value = dict(FORM)
        yield SimpleNamespace(command=command, note=note, find=find, load=load, state=state)


def test_form_page_renders_with_note_and_base_path():
    with patch(f"{MODULE}.render_to_string", return_value="<html>") as render:
        [response] = _api(query={"note_id": NOTE}).form_page()
    assert response.status_code == HTTPStatus.OK
    assert response.content == b"<html>"
    render.assert_called_once_with(
        "templates/form.html",
        {"note_id": NOTE, "base_path": "/plugin-io/api/conditional_questionnaire"},
    )


@pytest.mark.parametrize("query", [{}, {"note_id": "not-a-uuid"}])
def test_form_page_needs_a_note(query):
    [response] = _api(query=query).form_page()
    assert response.status_code == HTTPStatus.BAD_REQUEST


def test_list_questionnaires():
    with patch(f"{MODULE}.charting_questionnaires", return_value=[{"id": "a", "name": "A"}]):
        [response] = _api().list_questionnaires()
    assert _json(response) == {"questionnaires": [{"id": "a", "name": "A"}]}


def test_get_questionnaire(models):
    [response] = _api(path={"questionnaire_id": QUESTIONNAIRE_ID}).get_questionnaire()
    assert _json(response)["name"] == "Intro"
    models.find.assert_called_once_with(QUESTIONNAIRE_ID)


def test_get_questionnaire_bad_id(models):
    [response] = _api(path={"questionnaire_id": "nope"}).get_questionnaire()
    assert response.status_code == HTTPStatus.NOT_FOUND
    models.find.assert_not_called()


def test_get_questionnaire_unknown(models):
    models.find.return_value = None
    [response] = _api(path={"questionnaire_id": QUESTIONNAIRE_ID}).get_questionnaire()
    assert response.status_code == HTTPStatus.NOT_FOUND


def test_save_originates_a_committed_command_with_visible_answers(models):
    with patch(f"{MODULE}.QuestionnaireCommand") as command_class:
        command_class.return_value.originate.return_value = "originate-effect"
        effect, response = _api(body=_body()).save()
    assert effect == "originate-effect"
    command_class.return_value.originate.assert_called_once_with(commit=True)
    kwargs = command_class.call_args.kwargs
    assert kwargs["note_uuid"] == NOTE
    assert kwargs["command_uuid"] == COMMAND
    assert kwargs["questionnaire_id"] == QUESTIONNAIRE_ID
    assert [(a.question_id, a.response) for a in kwargs["answers"]] == [(1, 12)]
    assert response.status_code == HTTPStatus.CREATED
    assert _json(response) == {
        "status": "saved",
        "command_uuid": COMMAND,
        "saved_question_ids": [1],
    }


def test_save_on_a_note_without_state(models):
    models.note.objects.filter.return_value.select_related.return_value.first.return_value = (
        SimpleNamespace()
    )
    with patch(f"{MODULE}.QuestionnaireCommand"):
        _, response = _api(body=_body()).save()
    assert response.status_code == HTTPStatus.CREATED


def test_save_is_idempotent(models):
    models.command.objects.filter.return_value.exists.return_value = True
    [response] = _api(body=_body()).save()
    assert _json(response) == {"status": "already_saved", "command_uuid": COMMAND}
    models.command.objects.filter.assert_called_once_with(id=COMMAND)
    models.note.objects.filter.assert_not_called()


@pytest.mark.parametrize(
    "body",
    [
        ["not", "an", "object"],
        _body(note_id="x"),
        _body(questionnaire_id=None),
        _body(command_uuid=5),
    ],
)
def test_save_rejects_bad_bodies(models, body):
    [response] = _api(body=body).save()
    assert response.status_code == HTTPStatus.BAD_REQUEST


def test_save_unknown_note(models):
    models.note.objects.filter.return_value.select_related.return_value.first.return_value = None
    [response] = _api(body=_body()).save()
    assert response.status_code == HTTPStatus.NOT_FOUND


def test_save_locked_note(models):
    models.state.editable.return_value = False
    [response] = _api(body=_body()).save()
    assert response.status_code == HTTPStatus.CONFLICT
    assert "locked" in _json(response)["error"]


def test_save_unknown_questionnaire(models):
    models.find.return_value = None
    [response] = _api(body=_body()).save()
    assert response.status_code == HTTPStatus.NOT_FOUND


def test_save_unsaveable_questionnaire(models):
    models.load.return_value = dict(FORM, saveable=False, reason="has DEC")
    [response] = _api(body=_body()).save()
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert _json(response) == {"error": "has DEC"}


def test_save_bad_answer(models):
    [response] = _api(body=_body(answers={"1": "99"})).save()
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert "no option" in _json(response)["error"]
