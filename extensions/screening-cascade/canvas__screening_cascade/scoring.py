"""Pure scoring helpers: total a questionnaire, compare, describe."""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable  # noqa: UP035 - install lint rejects collections.abc

if TYPE_CHECKING:
    from canvas__screening_cascade.config import Rule

# Lambdas, not the operator module: the plugin sandbox does not allow operator.
_COMPARE = {
    ">=": lambda a, b: a >= b,
    ">": lambda a, b: a > b,
    "<=": lambda a, b: a <= b,
    "<": lambda a, b: a < b,
    "==": lambda a, b: a == b,
}


def total_score(
    answers: Iterable[tuple[object, str | None]], scorable_question_ids: set[object]
) -> float | None:
    """Sum the response-option values of a fully answered questionnaire.

    ``answers`` is (question id, response option value) pairs. Returns None
    when a scorable question has no answer or a value is not a number, because
    a partial or unreadable total would understate the result.
    """
    total = 0.0
    answered: set[object] = set()
    for question_id, value in answers:
        if question_id not in scorable_question_ids:
            continue
        try:
            total += float(value) if value not in (None, "") else 0.0
        except (TypeError, ValueError):
            return None
        answered.add(question_id)
    if not scorable_question_ids or answered != scorable_question_ids:
        return None
    return total


def passes(rule: Rule, score: float) -> bool:
    """True if the score crosses the rule's threshold."""
    if rule.operator is None or rule.threshold is None:
        return False
    return bool(_COMPARE[rule.operator](score, rule.threshold))


def narrative(rule: Rule, score: float) -> str:
    """'Score: 4. Positive screen, PHQ-9 recommended.' style text."""
    shown = int(score) if float(score).is_integer() else round(score, 2)
    # Bands are inclusive. A score outside every band (including a fractional
    # score in a gap between whole-number bands) gets no label rather than a
    # guessed one; the abnormal flag still carries the threshold result.
    label = next((b.label for b in rule.bands if b.min <= score <= b.max), None)
    return f"Score: {shown}. {label}." if label else f"Score: {shown}."
