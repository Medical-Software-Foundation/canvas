"""Score completed interviews and decide whether a score fires a rule.

Canvas stores scoring metadata on the Questionnaire (``scoring_function_name``,
``scoring_code``) but does not expose the computed score on the Interview, so the
score is summed here from the recorded responses.

The instruments this plugin pairs (PHQ-2, GAD-2 and their kin) are sums of
per-question ordinal values, which is what ``response_option_value`` holds. An
instrument scored any other way - weighted items, a non-numeric answer set - sums
to None here, and is paired with the ``completed`` comparator instead.
"""

from typing import Any

from canvas_sdk.v1.data.questionnaire import Interview, InterviewQuestionResponse
from logger import log

from questionnaire_followup.services.config_store import (
    COMPARATOR_AT_LEAST,
    COMPARATOR_AT_MOST,
    COMPARATOR_BETWEEN,
    COMPARATOR_COMPLETED,
    DEFAULT_COMPARATOR,
)

# (interview primary key, questionnaire code) - the unit a score belongs to.
ScoreKey = tuple[int, str]


def _numeric(raw: Any) -> int | None:
    """Read an ordinal response value as an int, or None when it is not numeric."""
    if raw is None:
        return None
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def score_interviews(screens: list[tuple[Interview, str]]) -> dict[ScoreKey, int | None]:
    """Score each (interview, questionnaire code) pair, reading every response in one query.

    Each pair maps, keyed by ``(interview.pk, code)``, to the sum of the numeric
    responses that interview recorded for that questionnaire - or None when nothing
    numeric was recorded. An un-scoreable interview must not be read as a zero, and
    must not be read as positive either; callers treat None as "cannot tell" and do
    not fire the pairing.

    This runs on the portal's hot path, so it issues one query however many screens
    are being scored.
    """
    scores: dict[ScoreKey, int | None] = {
        (interview.pk, code): None for interview, code in screens
    }
    if not scores:
        return scores

    try:
        responses = InterviewQuestionResponse.objects.filter(
            interview_id__in={pk for pk, _code in scores},
            questionnaire__code__in={code for _pk, code in scores},
        ).values_list(
            "interview_id", "questionnaire__code", "response_option_value", "response_option__value"
        )
        for interview_pk, code, recorded, option_default in responses:
            key = (interview_pk, code)
            if key not in scores:
                continue  # a wanted interview and a wanted code, but not paired together
            # What was recorded on the response wins; the option's own value is the
            # fallback for questionnaires that leave the recorded value blank.
            value = _numeric(recorded)
            if value is None:
                value = _numeric(option_default)
            if value is None:
                continue
            scores[key] = (scores[key] or 0) + value
    except (AttributeError, ValueError) as exc:
        log.warning(f"could not read responses for interviews {sorted(scores)}: {exc}")
        return dict.fromkeys(scores)

    return scores


def needs_score(rule: dict[str, Any]) -> bool:
    """Whether this rule's comparator reads a score at all.

    A rule that pairs on completion alone does not, so a portal load where every
    rule is of that kind never runs the scoring query.
    """
    comparator: str = rule.get("comparator", DEFAULT_COMPARATOR)
    return comparator != COMPARATOR_COMPLETED


def matches(score: int | None, rule: dict[str, Any]) -> bool:
    """Whether a screen's score fires this rule's comparator.

    An unscoreable screen (None) never fires a comparator that reads a score.
    That matters most for ``at_most``: reading None as a zero would put a
    follow-up in front of every patient whose instrument is not a sum of
    ordinals. ``completed`` is the one comparator that ignores the score, which
    is how such an instrument can be paired at all.
    """
    comparator: str = rule.get("comparator", DEFAULT_COMPARATOR)
    if comparator == COMPARATOR_COMPLETED:
        return True
    if score is None:
        return False
    threshold: int = rule["threshold"]
    if comparator == COMPARATOR_AT_LEAST:
        return score >= threshold
    if comparator == COMPARATOR_AT_MOST:
        return score <= threshold
    if comparator == COMPARATOR_BETWEEN:
        # A backwards range (low end above the high end) matches nothing, on
        # purpose: the editor flags it rather than swapping the two, because a
        # silent swap would point the rule at a severity band nobody chose.
        threshold_max: int = rule["threshold_max"]
        return threshold <= score <= threshold_max
    # A comparator this version does not know. active_rules drops these before
    # they reach here; refusing to fire is the backstop if one ever does.
    return False
