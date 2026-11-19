from http import HTTPStatus
from typing import Any
from uuid import UUID

from canvas_sdk.commands.commands.questionnaire import QuestionnaireCommand
from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.note import Note
from logger import log

from conditional_questionnaire.services.answers import (
    AnswerError,
    clean_answers,
    command_answers,
)
from conditional_questionnaire.services.questionnaire_form import (
    charting_questionnaires,
    find_questionnaire,
    load_form,
)

PLUGIN_NAME = "conditional_questionnaire"
BASE_PATH = f"/plugin-io/api/{PLUGIN_NAME}"


def _is_uuid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def _error(message: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST) -> list[Response | Effect]:
    return [JSONResponse({"error": message}, status_code=status)]


class ConditionalQuestionnaireAPI(StaffSessionAuthMixin, SimpleAPI):
    """Serves the form page, the questionnaires and their rules, and the save endpoint.

    Every route needs a logged-in staff session, so a saved questionnaire is
    attributed to the provider who filled it in.
    """

    @api.get("/form")
    def form_page(self) -> list[Response | Effect]:
        """The form page. The note it saves to comes from the launch URL."""
        note_id = self.request.query_params.get("note_id", "")
        if not _is_uuid(note_id):
            return _error("A note id is required")
        html = render_to_string(
            "templates/form.html",
            {"note_id": note_id, "base_path": BASE_PATH},
        )
        return [HTMLResponse(html, status_code=HTTPStatus.OK)]

    @api.get("/questionnaires")
    def list_questionnaires(self) -> list[Response | Effect]:
        """Every active questionnaire a provider can add to a note."""
        return [JSONResponse({"questionnaires": charting_questionnaires()})]

    @api.get("/questionnaires/<questionnaire_id>")
    def get_questionnaire(self) -> list[Response | Effect]:
        """One questionnaire's questions, options and Field Rules."""
        questionnaire_id = self.request.path_params["questionnaire_id"]
        if not _is_uuid(questionnaire_id):
            return _error("Unknown questionnaire", HTTPStatus.NOT_FOUND)
        questionnaire = find_questionnaire(questionnaire_id)
        if questionnaire is None:
            return _error("Unknown questionnaire", HTTPStatus.NOT_FOUND)
        return [JSONResponse(load_form(questionnaire))]

    @api.post("/save")
    def save(self) -> list[Response | Effect]:
        """Record the visible answers as a committed Questionnaire command in the note.

        The browser picks ``command_uuid`` once per form, so a retried save after a
        dropped response finds the command already there and doesn't add a second one.
        """
        body = self.request.json()
        if not isinstance(body, dict):
            return _error("Expected a JSON object")
        note_id = body.get("note_id")
        questionnaire_id = body.get("questionnaire_id")
        command_uuid = body.get("command_uuid")
        if not (_is_uuid(note_id) and _is_uuid(questionnaire_id) and _is_uuid(command_uuid)):
            return _error("note_id, questionnaire_id and command_uuid must be ids")

        if Command.objects.filter(id=command_uuid).exists():
            return [JSONResponse({"status": "already_saved", "command_uuid": command_uuid})]

        note = Note.objects.filter(id=note_id).select_related("current_state").first()
        if note is None:
            return _error("Unknown note", HTTPStatus.NOT_FOUND)
        current_state = getattr(note, "current_state", None)
        if current_state is not None and not current_state.editable():
            return _error(
                "This note is locked. Unlock it to add a questionnaire.", HTTPStatus.CONFLICT
            )
        questionnaire = find_questionnaire(str(questionnaire_id))
        if questionnaire is None:
            return _error("Unknown questionnaire", HTTPStatus.NOT_FOUND)

        form = load_form(questionnaire)
        if not form["saveable"]:
            return _error(form["reason"], HTTPStatus.UNPROCESSABLE_ENTITY)
        try:
            cleaned = clean_answers(form["questions"], body.get("answers", {}))
        except AnswerError as error:
            return _error(str(error))
        answers = command_answers(form["questions"], cleaned)

        command = QuestionnaireCommand(
            note_uuid=str(note_id),
            command_uuid=str(command_uuid),
            questionnaire_id=str(questionnaire.id),
            answers=answers,
        )
        log.info(
            f"Saving questionnaire {questionnaire.id} to note {note_id} "
            f"with {len(answers)} of {len(form['questions'])} questions answered"
        )
        return [
            command.originate(commit=True),
            JSONResponse(
                {
                    "status": "saved",
                    "command_uuid": command_uuid,
                    "saved_question_ids": [answer.question_id for answer in answers],
                },
                status_code=HTTPStatus.CREATED,
            ),
        ]
