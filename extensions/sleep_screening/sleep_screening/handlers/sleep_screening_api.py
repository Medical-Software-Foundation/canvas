import json
from datetime import date
from http import HTTPStatus
from typing import Union
from uuid import uuid4

from canvas_sdk.commands import DiagnoseCommand, QuestionnaireCommand, TaskCommand
from canvas_sdk.commands.commands.task import AssigneeType, TaskAssigner
from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.note import Note
from canvas_sdk.v1.data.questionnaire import Interview, Questionnaire
from logger import log

from sleep_screening.patient_context import build_context
from sleep_screening.scoring.registry import QUESTIONNAIRE_CODES, get_scorer
from sleep_screening.sleep_codes import load_codes, preselect_for


def _json_for_script(value: str) -> str:
    """JSON-encode for safe embedding in an inline <script> block. json.dumps
    does not escape '<', so a '</script>' payload could break out of the tag."""
    return json.dumps(value).replace("<", "\\u003c")


def _instrument_structure(code: str) -> dict | None:
    """Read an installed questionnaire's questions + options from the data model,
    so the in-app form always matches what will commit. None if not installed."""
    questionnaire = (
        Questionnaire.objects.filter(code=code)
        .prefetch_related("questions__response_option_set__options")
        .first()
    )
    if questionnaire is None:
        return None
    questions = []
    for question in questionnaire.questions.all():
        option_set = question.response_option_set
        options = []
        if option_set is not None:
            for option in option_set.options.all():
                options.append(
                    {"name": option.name, "code": option.code, "value": option.value}
                )
        questions.append(
            {"code": question.code, "content": question.name, "options": options}
        )
    return {"code": code, "name": questionnaire.name, "questions": questions}


def _note_dbid_from_uuid(note_uuid: str):
    """Resolve a note UUID to its integer dbid (Interview links by note dbid).
    Returns None if not found."""
    if not note_uuid:
        return None
    try:
        return Note.objects.get(id=note_uuid).dbid
    except Note.DoesNotExist:
        return None


def _committed_instruments(note_uuid: str) -> dict:
    """Return {instrument_code: {score, band, narrative, abnormal}} for our
    instruments already committed on this note, so the tab can show them
    read-only instead of letting the provider re-administer them."""
    note_dbid = _note_dbid_from_uuid(note_uuid)
    if note_dbid is None:
        return {}

    interviews = (
        Interview.objects.filter(
            note_id=note_dbid,
            committer__isnull=False,
            deleted=False,
            entered_in_error__isnull=True,
            questionnaires__code__in=QUESTIONNAIRE_CODES,
        )
        .prefetch_related(
            "questionnaires",
            "interview_responses__response_option",
            "interview_responses__question",
        )
    )

    out: dict = {}
    for interview in interviews:
        questionnaire = interview.questionnaires.first()
        code = questionnaire.code if questionnaire else None
        scorer = get_scorer(code) if code else None
        if scorer is None or code in out:
            continue
        responses = {}
        for resp in interview.interview_responses.all():
            option = resp.response_option
            question = resp.question
            if option is None or question is None:
                continue
            try:
                responses[question.code] = float(option.value)
            except (ValueError, TypeError):
                continue
        patient_id = str(interview.patient.id) if interview.patient else ""
        result = scorer(responses, build_context(patient_id, date.today()))
        out[code] = {
            "score": result.score,
            "band": result.band,
            "narrative": result.narrative,
            "abnormal": result.abnormal,
        }
    return out


class SleepScreeningAPI(StaffSessionAuthMixin, SimpleAPI):
    """Serves the Sleep Screening UI and the commit/stage endpoints."""

    PREFIX = "/screening"

    @api.get("/app")
    def get_app(self) -> list[Union[Response, Effect]]:
        note_id = self.request.query_params.get("note_id", "")
        patient_id = self.request.query_params.get("patient_id", "")
        if not note_id:
            return [
                HTMLResponse(
                    "<html><body>Error: note_id is required</body></html>",
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        html = render_to_string(
            "templates/sleep_screening.html",
            {
                "note_id_json": _json_for_script(note_id),
                "patient_id_json": _json_for_script(patient_id),
            },
        )
        return [HTMLResponse(html)]

    @api.get("/context")
    def get_context(self) -> list[Union[Response, Effect]]:
        patient_id = self.request.query_params.get("patient_id", "")
        if not patient_id:
            return [
                JSONResponse(
                    {"error": "patient_id required"}, status_code=HTTPStatus.BAD_REQUEST
                )
            ]
        ctx = build_context(patient_id, date.today())
        return [
            JSONResponse(
                {
                    "age": ctx.age,
                    "sex": ctx.sex,
                    "bmi": round(ctx.bmi, 1) if ctx.bmi is not None else None,
                    "bmi_available": ctx.bmi is not None,
                }
            )
        ]

    @api.get("/instruments")
    def instruments(self) -> list[Union[Response, Effect]]:
        """Return the three instrument structures, the diagnosis code menu, and
        which instruments are already committed on this note (for read-only)."""
        note_id = self.request.query_params.get("note_id", "")
        committed = _committed_instruments(note_id)
        out = []
        for code in QUESTIONNAIRE_CODES:
            structure = _instrument_structure(code)
            if structure is not None:
                structure["preselect_dx"] = preselect_for(code)
                structure["committed"] = committed.get(code)
                out.append(structure)
        return [
            JSONResponse(
                {"instruments": out, "diagnosis_codes": load_codes(self.secrets)}
            )
        ]

    @api.post("/commit-instrument")
    def commit_instrument(self) -> list[Union[Response, Effect]]:
        body = self.request.json() or {}
        note_id = body.get("note_id", "")
        instrument = body.get("instrument", "")
        responses = body.get("responses", {})
        if not note_id or not instrument:
            return [
                JSONResponse(
                    {"error": "note_id and instrument required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        if instrument not in QUESTIONNAIRE_CODES:
            return [
                JSONResponse(
                    {"error": "unknown instrument: " + instrument},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        # Guard against re-committing an instrument already committed on this
        # note (e.g. a stale tab that did not see the committed state).
        if instrument in _committed_instruments(note_id):
            return [
                JSONResponse(
                    {"error": "already committed: " + instrument},
                    status_code=HTTPStatus.CONFLICT,
                )
            ]

        questionnaire = Questionnaire.objects.filter(code=instrument).first()
        if questionnaire is None:
            return [
                JSONResponse(
                    {"error": "questionnaire not installed: " + instrument},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        command = QuestionnaireCommand(
            questionnaire_id=str(questionnaire.id), note_uuid=note_id
        )
        command.command_uuid = str(uuid4())
        answers = responses if isinstance(responses, dict) else {}
        for question in command.questions:
            question_code = question.coding.get("code")
            selected = answers.get(question_code)
            if selected is None:
                continue
            for option in question.options:
                if option.code == selected:
                    question.add_response(option=option)
        return [command.originate(), command.edit(), command.commit()]

    @api.post("/stage-next-steps")
    def stage_next_steps(self) -> list[Union[Response, Effect]]:
        body = self.request.json() or {}
        note_id = body.get("note_id", "")
        if not note_id:
            return [
                JSONResponse(
                    {"error": "note_id required"}, status_code=HTTPStatus.BAD_REQUEST
                )
            ]

        selected = body.get("selected_diagnoses", [])
        modality = body.get("study_modality", "")
        comment = body.get("comment", "")

        effects: list[Union[Response, Effect]] = []
        for icd10 in selected:
            if icd10:
                effects.append(
                    DiagnoseCommand(note_uuid=note_id, icd10_code=str(icd10)).originate()
                )

        title = "Order sleep study - " + modality if modality else "Order sleep study"
        task = TaskCommand(
            note_uuid=note_id,
            title=title,
            assign_to=TaskAssigner(to=AssigneeType.UNASSIGNED),
            comment=comment,
        )
        effects.append(task.originate())
        log.info(
            "sleep_screening: staged "
            + str(len(selected))
            + " diagnosis(es) + sleep-study task for note "
            + str(note_id)
        )
        return effects
