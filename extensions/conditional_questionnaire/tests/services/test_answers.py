import pytest
from canvas_sdk.commands.commands.questionnaire import Selection

from conditional_questionnaire.services.answers import (
    AnswerError,
    clean_answers,
    command_answers,
)

OPTIONS = [
    {"id": 11, "name": "Yes", "code": "Y", "value": "y"},
    {"id": 12, "name": "No", "code": "N", "value": "n"},
]
QUESTIONS = [
    {"id": 1, "name": "Smoker", "type": "SING", "options": OPTIONS, "rule": None},
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
    {"id": 3, "name": "Symptoms", "type": "MULT", "options": OPTIONS, "rule": None},
    {"id": 4, "name": "Last visit", "type": "DATE", "options": [], "rule": None},
    {"id": 5, "name": "Age", "type": "INT", "options": [], "rule": None},
]


def test_clean_answers_accepts_each_type():
    cleaned = clean_answers(
        QUESTIONS,
        {
            "1": "11",
            "2": " two ",
            "3": ["11", "12", "11"],
            "4": "2026-01-02",
            "5": "40",
            "99": "not on the form",
        },
    )
    assert cleaned == {"1": "11", "2": "two", "3": ["11", "12"], "4": "2026-01-02"}


def test_clean_answers_drops_blanks_and_none():
    cleaned = clean_answers(QUESTIONS, {"1": "", "2": "  ", "3": [], "4": " ", "5": None})
    assert cleaned == {}
    assert clean_answers(QUESTIONS, {"2": None}) == {}


def test_clean_answers_needs_an_object():
    with pytest.raises(AnswerError):
        clean_answers(QUESTIONS, ["1"])


@pytest.mark.parametrize(
    "submitted",
    [
        {"1": "99"},
        {"2": 5},
        {"3": "11"},
        {"3": ["99"]},
        {"4": 20260102},
        {"4": "01/02/2026"},
    ],
)
def test_clean_answers_rejects_bad_values(submitted):
    with pytest.raises(AnswerError):
        clean_answers(QUESTIONS, submitted)


def test_command_answers_drops_hidden_and_converts_types():
    answers = command_answers(
        QUESTIONS, {"1": "12", "2": "stale", "3": ["11", "12"], "4": "2026-01-02"}
    )
    assert [a.question_id for a in answers] == [1, 3, 4]
    assert answers[0].response == 12
    assert answers[1].response == [Selection(option_id=11), Selection(option_id=12)]
    assert answers[2].response == "2026-01-02"


def test_command_answers_keeps_shown_dependents():
    answers = command_answers(QUESTIONS, {"1": "11", "2": "a pack a day"})
    assert [(a.question_id, a.response) for a in answers] == [(1, 11), (2, "a pack a day")]
