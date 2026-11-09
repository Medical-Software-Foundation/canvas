"""Check what the browser sent and turn the visible answers into command answers."""

from datetime import date
from typing import Any

from canvas_sdk.commands.commands.questionnaire import Answer, Selection

from conditional_questionnaire.services.questionnaire_form import (
    ANSWERABLE_TYPES,
    TYPE_CHECKBOX,
    TYPE_DATE,
    TYPE_RADIO,
    TYPE_TEXT,
)
from conditional_questionnaire.services.rules import visible_answers


class AnswerError(ValueError):
    """A submitted answer that doesn't fit its question."""


def clean_answers(questions: list[dict[str, Any]], submitted: Any) -> dict[str, Any]:
    """The submitted answers, checked against each question's type and options.

    Keys are question ids as text. A question that isn't on the form, or whose type
    this plugin doesn't record, is dropped. A value that doesn't fit its question
    raises ``AnswerError``.
    """
    if not isinstance(submitted, dict):
        raise AnswerError("answers must be an object keyed by question id")
    cleaned: dict[str, Any] = {}
    for question in questions:
        key = str(question["id"])
        if key not in submitted or question["type"] not in ANSWERABLE_TYPES:
            continue
        value = _clean_one(question, submitted[key])
        if value is not None:
            cleaned[key] = value
    return cleaned


def _option_ids(question: dict[str, Any]) -> set[str]:
    return {str(option["id"]) for option in question["options"]}


def _clean_one(question: dict[str, Any], raw: Any) -> Any:
    kind = question["type"]
    label = question["name"]
    if raw is None:
        return None
    if kind == TYPE_TEXT:
        if not isinstance(raw, str):
            raise AnswerError(f"'{label}' takes text")
        return raw.strip() or None
    if kind == TYPE_DATE:
        if not isinstance(raw, str):
            raise AnswerError(f"'{label}' takes a date")
        text = raw.strip()
        if not text:
            return None
        try:
            date.fromisoformat(text)
        except ValueError as error:
            raise AnswerError(f"'{label}' takes a date as YYYY-MM-DD") from error
        return text
    if kind == TYPE_RADIO:
        if raw == "":
            return None
        if str(raw) not in _option_ids(question):
            raise AnswerError(f"'{label}' has no option {raw!r}")
        return str(raw)
    # TYPE_CHECKBOX, the last answerable type.
    if not isinstance(raw, list):
        raise AnswerError(f"'{label}' takes a list of options")
    allowed = _option_ids(question)
    picks = []
    for pick in raw:
        if str(pick) not in allowed:
            raise AnswerError(f"'{label}' has no option {pick!r}")
        if str(pick) not in picks:
            picks.append(str(pick))
    return picks or None


def command_answers(questions: list[dict[str, Any]], cleaned: dict[str, Any]) -> list[Answer]:
    """``Answer`` objects for the questions that show, in questionnaire order.

    Field Rules are re-run here, so an answer to a hidden question is never saved.
    """
    kept = visible_answers(questions, cleaned)
    answers = []
    for question in questions:
        key = str(question["id"])
        if key not in kept:
            continue
        value = kept[key]
        response: str | int | list[Selection]
        if question["type"] == TYPE_CHECKBOX:
            response = [Selection(option_id=int(pick)) for pick in value]
        elif question["type"] == TYPE_RADIO:
            response = int(value)
        else:
            response = value
        answers.append(Answer(question_id=int(question["id"]), response=response))
    return answers
