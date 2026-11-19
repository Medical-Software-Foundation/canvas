import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from canvas_sdk.commands.commands.questionnaire import Answer, Selection
from canvas_sdk.commands.commands.questionnaire.question import ResponseOption

from charting_tools.api.templates_api import NoteTemplatesAPI, validate_payload
from charting_tools.questionnaires import answers_for, clean_answers, question_form
from tests.conftest import make_note, make_request, make_template, payload


def _q(qid: int, qtype: str, code: str = "", label: str = "Q", options: list | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=qid, type=qtype, label=label, coding={"system": "LOINC", "code": code}, options=options or []
    )


def _opt(dbid: int, code: str) -> ResponseOption:
    return ResponseOption(dbid=dbid, name=f"opt {code}", code=code, value=code)


def test_clean_answers() -> None:
    assert clean_answers({"a": "x", "b": "", "c": [], "d": ["1", ""], "e": 3, "f": True, "g": None}) == {
        "a": "x",
        "d": ["1"],
        "e": 3,
    }
    assert clean_answers("nope") == {}


def test_answers_map_codes_to_current_version_ids() -> None:
    command = SimpleNamespace(
        questions=[
            _q(11, "SING", "c1", options=[_opt(101, "yes"), _opt(102, "no")]),
            _q(12, "MULT", "c2", options=[_opt(201, "a"), _opt(202, "b"), _opt(203, "c")]),
            _q(13, "INT", "c3"),
            _q(14, "TXT", "", label="Notes"),
            _q(15, "DATE", "c5"),
            _q(16, "SING", "c6", options=[_opt(301, "x")]),
        ]
    )
    stored = {
        "LOINC|c1": "no",
        "LOINC|c2": ["c", "a", "gone"],
        "LOINC|c3": "7",
        "label|Notes": "Normal",
        "LOINC|c5": "2026-10-01",
        "LOINC|c6": "retired-option",
        "LOINC|old": "question removed in new version",
    }
    assert answers_for(command, stored) == [
        Answer(question_id=11, response=102),
        Answer(question_id=12, response=[Selection(option_id=203), Selection(option_id=201)]),
        Answer(question_id=13, response=7),
        Answer(question_id=14, response="Normal"),
        Answer(question_id=15, response="2026-10-01"),
    ]


def test_answers_skip_non_numeric_integer() -> None:
    command = SimpleNamespace(questions=[_q(1, "INT", "n")])
    assert answers_for(command, {"LOINC|n": "lots"}) == []


def test_question_form_shape() -> None:
    option_set = MagicMock(type="SING")
    option_set.options.order_by.return_value = [SimpleNamespace(code="Y", name="Yes"), SimpleNamespace(code="", name="Unsure")]
    text_set = MagicMock(type="TXT")
    questionnaire = MagicMock()
    questionnaire.questions.select_related.return_value.prefetch_related.return_value = [
        SimpleNamespace(code="c1", code_system="LOINC", name="Smoker?", response_option_set=option_set),
        SimpleNamespace(code="", code_system="", name="Comments", response_option_set=text_set),
        SimpleNamespace(code="c3", code_system="LOINC", name="Unsupported", response_option_set=MagicMock(type="XYZ")),
    ]
    assert question_form(questionnaire) == [
        {"key": "LOINC|c1", "label": "Smoker?", "type": "SING",
         "options": [{"key": "Y", "label": "Yes"}, {"key": "Unsure", "label": "Unsure"}]},
        {"key": "label|Comments", "label": "Comments", "type": "TXT", "options": []},
    ]


def test_validation_keeps_answers_only_on_questionnaire_commands() -> None:
    fields, error = validate_payload(
        {
            "name": "A",
            "commands": [
                {"schema_key": "ros", "questionnaire": {"code_system": "S", "code": "R"}, "answers": {"S|q": "x"}},
                {"schema_key": "plan", "answers": {"S|q": "x"}},
            ],
        }
    )
    assert error is None and fields is not None
    assert fields["commands"][0]["answers"] == {"S|q": "x"}
    assert "answers" not in fields["commands"][1]


def test_questions_route(mocker: MagicMock) -> None:
    mocker.patch("charting_tools.api.templates_api.staff_can_manage_templates", return_value=True)
    resolve = mocker.patch("charting_tools.api.templates_api.resolve")
    resolve.return_value = {("ROS", "S", "R"): "qn"}
    mocker.patch("charting_tools.api.templates_api.question_form", return_value=[{"key": "k"}])
    api = object.__new__(NoteTemplatesAPI)
    api.request = make_request()
    api.request.query_params = {"schema_key": "ros", "code_system": "S", "code": "R"}
    api.secrets = {}
    [response] = api.questionnaire_questions()
    resolve.assert_called_once_with({("ROS", "S", "R")})
    assert json.loads(response.content) == {"questions": [{"key": "k"}]}


def test_insert_sends_answers(mocker: MagicMock) -> None:
    from canvas_sdk.commands import ReviewOfSystemsCommand

    from charting_tools.insertion import template_effects

    mocker.patch("charting_tools.insertion.resolve", return_value={("ROS", "S", "R"): SimpleNamespace(id="rosuuid")})
    question = _q(5, "SING", "q", options=[_opt(50, "neg")])
    question.name = "question-5"
    question.response = None
    question.add_response = lambda option: setattr(question, "response", option.dbid)
    mocker.patch.object(ReviewOfSystemsCommand, "questions", new_callable=mocker.PropertyMock, return_value=[question])
    template = make_template(
        commands=[{"schema_key": "ros", "questionnaire": {"code_system": "S", "code": "R"}, "answers": {"LOINC|q": "neg"}}]
    )
    data = payload(template_effects(template, make_note(), {}, replace_line=True)[0])["data"]
    assert data["commands"][0]["data"]["questionnaire_id"] == "rosuuid"
    assert data["commands"][0]["data"]["questions"] == {"question-5": 50}
