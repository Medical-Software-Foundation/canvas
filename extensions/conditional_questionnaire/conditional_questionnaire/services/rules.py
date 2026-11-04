"""Field Rule evaluation for Questionnaire Builder questionnaires.

A question with Field Rules carries a ``rule``:

    {"behavior": "all" | "any", "conditions": [{"on": <question id>, "op": <operator>,
                                                 "option": <option id or None>,
                                                 "value": <text or None>}]}

The operators are the four ``QuestionEnablementCondition.operator`` values: ``=``,
``!=``, ``exists`` and ``not_exists``. Semantics follow the builder's Preview tab:

- A hidden question counts as unanswered, so hiding one question hides everything
  that depends on it (chains collapse).
- ``exists`` / ``not_exists`` test whether the controlling question has an answer.
- ``=`` / ``!=`` hold only once the controlling question has an answer.

``templates/form.html`` mirrors these functions in JavaScript so questions show and
hide as the provider types; the save endpoint re-runs them here so an answer to a
hidden question is never saved, whatever the browser sends.
"""

from typing import Any

OP_EQUALS = "="
OP_NOT_EQUALS = "!="
OP_EXISTS = "exists"
OP_NOT_EXISTS = "not_exists"
KNOWN_OPERATORS = frozenset({OP_EQUALS, OP_NOT_EQUALS, OP_EXISTS, OP_NOT_EXISTS})

BEHAVIOR_ALL = "all"
BEHAVIOR_ANY = "any"


def has_answer(answer: Any) -> bool:
    """Whether an answer counts as given (blank text and an empty pick list do not)."""
    if answer is None:
        return False
    if isinstance(answer, str):
        return bool(answer.strip())
    if isinstance(answer, list):
        return bool(answer)
    return True


def _option_texts(question: dict[str, Any], option_id: Any) -> set[str]:
    """The folded name, code and value of one of a question's options."""
    for option in question.get("options", []):
        if str(option["id"]) == str(option_id):
            return {
                str(option.get(key) or "").strip().casefold()
                for key in ("name", "code", "value")
                if str(option.get(key) or "").strip()
            }
    return set()


def condition_met(
    condition: dict[str, Any],
    answers: dict[str, Any],
    questions_by_id: dict[str, dict[str, Any]],
) -> bool:
    """One condition against the answers that currently count."""
    answer = answers.get(str(condition["on"]))
    present = has_answer(answer)
    operator = condition["op"]
    if operator == OP_EXISTS:
        return present
    if operator == OP_NOT_EXISTS:
        return not present
    if not present:
        return False

    picks = answer if isinstance(answer, list) else [answer]
    if condition.get("option") is not None:
        equal = any(str(pick) == str(condition["option"]) for pick in picks)
    else:
        wanted = str(condition.get("value") or "").strip().casefold()
        controlling = questions_by_id.get(str(condition["on"]), {})
        equal = False
        for pick in picks:
            texts = _option_texts(controlling, pick) or {str(pick).strip().casefold()}
            if wanted in texts:
                equal = True
    return equal if operator == OP_EQUALS else not equal


def is_shown(
    question: dict[str, Any],
    answers: dict[str, Any],
    questions_by_id: dict[str, dict[str, Any]],
) -> bool:
    """Whether a question shows, given the answers that currently count."""
    rule = question.get("rule")
    if not rule or not rule.get("conditions"):
        return True
    results = [condition_met(cond, answers, questions_by_id) for cond in rule["conditions"]]
    return all(results) if rule.get("behavior") == BEHAVIOR_ALL else any(results)


def visible_answers(questions: list[dict[str, Any]], answers: dict[str, Any]) -> dict[str, Any]:
    """``answers`` without any answer to a question its rules hide.

    Worked to a fixed point: hiding one question can hide another that depends on it,
    and a condition may name a later question. Each pass only removes answers, so it
    ends within one pass per question.
    """
    questions_by_id = {str(question["id"]): question for question in questions}
    kept = {key: value for key, value in answers.items() if has_answer(value)}
    for _ in range(len(questions) + 1):
        dropped = [
            str(question["id"])
            for question in questions
            if str(question["id"]) in kept and not is_shown(question, kept, questions_by_id)
        ]
        if not dropped:
            break
        for question_id in dropped:
            kept.pop(question_id)
    return kept
