"""Read a Questionnaire Builder questionnaire, with its Field Rules, into a plain form.

A form is ``{"id", "name", "questions": [...], "saveable", "reason"}``. Each question is
``{"id", "name", "type", "options": [{"id", "name", "code", "value"}], "rule"}``, where
``rule`` is ``None`` (always shown) or the shape ``services/rules.py`` evaluates.
"""

from typing import Any

from canvas_sdk.v1.data.questionnaire import Questionnaire, QuestionnaireQuestionMap

from conditional_questionnaire.services.rules import (
    BEHAVIOR_ALL,
    BEHAVIOR_ANY,
    KNOWN_OPERATORS,
    OP_EQUALS,
    OP_NOT_EQUALS,
)

ACTIVE = "AC"
USE_CASE_QUESTIONNAIRE = "QUES"

TYPE_TEXT = "TXT"
TYPE_INTEGER = "INT"
TYPE_DECIMAL = "DEC"
TYPE_DATE = "DATE"
TYPE_RADIO = "SING"
TYPE_CHECKBOX = "MULT"

# Types this plugin records an answer for. The Questionnaire command saves text,
# single select, multi select and date answers; an integer answer is refused when the
# command is applied, so integer questions show in the form but can't be answered there.
ANSWERABLE_TYPES = frozenset({TYPE_TEXT, TYPE_DATE, TYPE_RADIO, TYPE_CHECKBOX})
# Types the SDK's QuestionnaireCommand can build at all. Any other type (decimal, for
# one) makes the command raise before it is sent, so that questionnaire can't be saved.
COMMAND_TYPES = ANSWERABLE_TYPES | {TYPE_INTEGER}


def charting_questionnaires() -> list[dict[str, str]]:
    """Every active questionnaire a provider can add to a note, by name."""
    rows = (
        Questionnaire.objects.filter(
            status=ACTIVE,
            can_originate_in_charting=True,
            use_case_in_charting=USE_CASE_QUESTIONNAIRE,
        )
        .order_by("name")
        .values_list("id", "name")
    )
    return [{"id": str(questionnaire_id), "name": name} for questionnaire_id, name in rows]


def find_questionnaire(questionnaire_id: str) -> Questionnaire | None:
    """The charting questionnaire with this id, or None when it isn't one."""
    return Questionnaire.objects.filter(
        id=questionnaire_id,
        status=ACTIVE,
        can_originate_in_charting=True,
        use_case_in_charting=USE_CASE_QUESTIONNAIRE,
    ).first()


def load_form(questionnaire: Questionnaire) -> dict[str, Any]:
    """The questionnaire's questions, in order, with options and active Field Rules.

    Three queries whatever the size: the question map with each question and option
    set, then the options and the conditions, both prefetched.
    """
    maps = (
        QuestionnaireQuestionMap.objects.filter(questionnaire=questionnaire, status=ACTIVE)
        .select_related("question__response_option_set")
        .prefetch_related(
            "question__response_option_set__options",
            "question__dependent_conditions",
        )
        .order_by("dbid")
    )
    questions = [row.question for row in maps if row.question is not None]
    return build_form(questionnaire, questions)


def build_form(questionnaire: Any, questions: list[Any]) -> dict[str, Any]:
    """Turn loaded questions into the form the page draws and the save endpoint checks."""
    on_form = {question.dbid for question in questions}
    fields = [_field(question, on_form) for question in questions]
    unsupported = sorted({field["type"] for field in fields if field["type"] not in COMMAND_TYPES})
    reason = ""
    if unsupported:
        reason = (
            "This questionnaire has a question type the Questionnaire command can't record "
            f"({', '.join(unsupported)}), so it can't be saved from here."
        )
    return {
        "id": str(questionnaire.id),
        "name": questionnaire.name,
        "questions": fields,
        "saveable": not unsupported,
        "reason": reason,
    }


def _field(question: Any, on_form: set[int]) -> dict[str, Any]:
    option_set = question.response_option_set
    options = []
    if option_set is not None:
        ordered = sorted(
            option_set.options.all(), key=lambda option: (option.ordering, option.dbid)
        )
        options = [
            {"id": option.dbid, "name": option.name, "code": option.code, "value": option.value}
            for option in ordered
            if option.status == ACTIVE
        ]
    return {
        "id": question.dbid,
        "name": question.name,
        "type": option_set.type if option_set is not None else "",
        "options": options,
        "rule": _rule(question, on_form),
    }


def _rule(question: Any, on_form: set[int]) -> dict[str, Any] | None:
    """The question's active Field Rules, or None when it always shows.

    A condition this plugin can't read (an unknown operator, or one that names a
    question not on this questionnaire) is left out instead of hiding the question
    for good: an extra question is a small cost, one that can never be answered isn't.
    No ``enable_behavior`` reads as "any", which is the same thing with one condition.
    """
    conditions = []
    for condition in question.dependent_conditions.all():
        operator = str(condition.operator or "").strip().lower()
        if condition.status != ACTIVE or operator not in KNOWN_OPERATORS:
            continue
        if condition.dependent_on_id not in on_form or condition.dependent_on_id == question.dbid:
            continue
        option_id = condition.answer_option_id
        value = str(condition.answer_value or "").strip() or None
        if operator in (OP_EQUALS, OP_NOT_EQUALS) and option_id is None and value is None:
            continue
        conditions.append(
            {"on": condition.dependent_on_id, "op": operator, "option": option_id, "value": value}
        )
    if not conditions:
        return None
    behavior = str(question.enable_behavior or "").strip().lower()
    return {
        "behavior": BEHAVIOR_ALL if behavior == BEHAVIOR_ALL else BEHAVIOR_ANY,
        "conditions": conditions,
    }
