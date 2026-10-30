"""Tests for summing ordinal answers and deciding whether a score fires a rule."""

from collections.abc import Callable
from unittest.mock import MagicMock, call, patch

import pytest
from canvas_sdk.test_utils.factories import PatientFactory
from canvas_sdk.v1.data import Questionnaire
from canvas_sdk.v1.data.questionnaire import Interview, InterviewQuestionResponse
from pytest_django import DjangoAssertNumQueries

from questionnaire_followup.services.config_store import new_rule
from questionnaire_followup.services.scoring import matches, needs_score, score_interviews

MODULE = "questionnaire_followup.services.scoring"
TRIGGER_CODE = "55758-7"

# The factory fixtures from conftest.py.
MakeQuestionnaire = Callable[..., Questionnaire]
MakeInterview = Callable[..., Interview]


# --------------------------------------------------------------------------- #
#  The score rules
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("comparator", "threshold", "threshold_max", "score", "expected"),
    [
        # "at least": the standard positive screen, inclusive at the cutoff.
        ("at_least", 3, 3, 2, False),
        ("at_least", 3, 3, 3, True),
        ("at_least", 3, 3, 9, True),
        # "at most": instruments where a LOW score is the concerning one.
        ("at_most", 2, 2, 3, False),
        ("at_most", 2, 2, 2, True),
        ("at_most", 2, 2, 0, True),
        # "between": a severity band, inclusive at both ends.
        ("between", 10, 14, 9, False),
        ("between", 10, 14, 10, True),
        ("between", 10, 14, 14, True),
        ("between", 10, 14, 15, False),
        # A backwards range is inert - never silently swapped into 10-14.
        ("between", 14, 10, 12, False),
        ("between", 14, 10, 10, False),
        ("between", 14, 10, 14, False),
        # "completed" ignores the score entirely.
        ("completed", 3, 3, 0, True),
        ("completed", 3, 3, 99, True),
    ],
)
def test_each_score_rule_fires_where_it_should(
    comparator: str, threshold: int, threshold_max: int, score: int, expected: bool
) -> None:
    """Every comparator, at and either side of its boundary."""
    rule = new_rule(comparator=comparator, threshold=threshold, threshold_max=threshold_max)

    assert matches(score, rule) is expected


@pytest.mark.parametrize("comparator", ["at_least", "at_most", "between"])
def test_an_unscoreable_screen_fires_no_scored_rule(comparator: str) -> None:
    """A screen we cannot score must never be read as a zero.

    This matters most for "at most": a zero would put the follow-up in front of
    every patient whose instrument is not a sum of ordinals.
    """
    assert matches(None, new_rule(comparator=comparator, threshold=3, threshold_max=14)) is False


def test_an_unscoreable_screen_still_fires_a_completion_rule() -> None:
    """Pairing on completion is how a non-numeric instrument is paired at all."""
    assert matches(None, new_rule(comparator="completed")) is True


def test_a_rule_with_no_comparator_still_means_at_least() -> None:
    """Rules stored before comparators existed keep their original meaning."""
    legacy = {"threshold": 3}

    assert matches(3, legacy) is True
    assert matches(2, legacy) is False


def test_a_score_rule_this_version_cannot_read_never_fires() -> None:
    """The backstop for a config written by a newer version of the plugin."""
    assert matches(3, new_rule(comparator="sometime_soon", threshold=3)) is False


def test_only_a_completion_rule_skips_scoring() -> None:
    """The scoring query is skipped only when no rule needs a score."""
    assert needs_score(new_rule(comparator="completed")) is False
    assert needs_score(new_rule(comparator="at_least")) is True
    assert needs_score({}) is True


# --------------------------------------------------------------------------- #
#  Against the test database
# --------------------------------------------------------------------------- #


def test_score_interviews_sums_each_screen_in_one_query(
    make_questionnaire: MakeQuestionnaire,
    make_interview: MakeInterview,
    django_assert_num_queries: DjangoAssertNumQueries,
) -> None:
    """Every screen is scored from a single read of the responses."""
    patient = PatientFactory.create()
    phq2 = make_questionnaire(TRIGGER_CODE, "PHQ-2")
    gad2 = make_questionnaire("69736-7", "GAD-2")
    depression = make_interview(patient, phq2, ["2", "3"])
    anxiety = make_interview(patient, gad2, ["0", "1"])

    with django_assert_num_queries(1):
        scores = score_interviews([(depression, TRIGGER_CODE), (anxiety, "69736-7")])

    assert scores == {(depression.pk, TRIGGER_CODE): 5, (anxiety.pk, "69736-7"): 1}


def test_score_interviews_returns_none_when_nothing_is_numeric(
    make_questionnaire: MakeQuestionnaire, make_interview: MakeInterview
) -> None:
    """A free-text instrument is unscoreable, not a zero."""
    patient = PatientFactory.create()
    trigger = make_questionnaire(TRIGGER_CODE, "PHQ-2")
    interview = make_interview(patient, trigger, ["often", "never"])

    assert score_interviews([(interview, TRIGGER_CODE)]) == {(interview.pk, TRIGGER_CODE): None}


def test_score_interviews_counts_only_each_screens_own_questionnaire(
    make_questionnaire: MakeQuestionnaire, make_interview: MakeInterview
) -> None:
    """Responses to another questionnaire in the same interview are not added in."""
    patient = PatientFactory.create()
    phq2 = make_questionnaire(TRIGGER_CODE, "PHQ-2")
    gad2 = make_questionnaire("69736-7", "GAD-2")
    intake = make_interview(patient, phq2, ["1", "1"])
    InterviewQuestionResponse.objects.create(
        interview=intake, questionnaire=gad2, response_option_value="3"
    )
    anxiety = make_interview(patient, gad2, ["2"])

    # Both codes and both interviews are in the query, but the intake's GAD-2
    # answer belongs to no requested pair and must not leak into either score.
    scores = score_interviews([(intake, TRIGGER_CODE), (anxiety, "69736-7")])

    assert scores == {(intake.pk, TRIGGER_CODE): 2, (anxiety.pk, "69736-7"): 2}


def test_score_interviews_with_no_screens_does_not_query(
    django_assert_num_queries: DjangoAssertNumQueries,
) -> None:
    """Nothing to score costs nothing."""
    with django_assert_num_queries(0):
        assert score_interviews([]) == {}


# --------------------------------------------------------------------------- #
#  Value precedence and failure, with the response query mocked
# --------------------------------------------------------------------------- #

READ_RESPONSES = [
    call.objects.filter(interview_id__in={7}, questionnaire__code__in={TRIGGER_CODE}),
    call.objects.filter().values_list(
        "interview_id", "questionnaire__code", "response_option_value", "response_option__value"
    ),
]


def test_score_interviews_prefers_the_recorded_value_over_the_option_value() -> None:
    """The recorded value wins; the option's own value only fills in when it is unusable."""
    interview = MagicMock()
    interview.pk = 7

    with patch(f"{MODULE}.InterviewQuestionResponse") as mock_responses:
        mock_responses.objects.filter.return_value.values_list.return_value = [
            (7, TRIGGER_CODE, "2", "0"),  # recorded value wins
            (7, TRIGGER_CODE, " 1 ", None),  # surrounding whitespace is tolerated
            (7, TRIGGER_CODE, "", "3"),  # blank recorded value -> option value
            (7, TRIGGER_CODE, "often", "1"),  # non-numeric recorded value -> option value
            (7, TRIGGER_CODE, None, None),  # nothing usable -> skipped, not counted as zero
        ]

        result = score_interviews([(interview, TRIGGER_CODE)])

        assert mock_responses.mock_calls == READ_RESPONSES
        assert interview.mock_calls == []
        assert result == {(7, TRIGGER_CODE): 7}


def test_score_interviews_returns_none_when_responses_cannot_be_read() -> None:
    """A failure reading the responses leaves every screen unscoreable, not zero."""
    interview = MagicMock()
    interview.pk = 7

    with (
        patch(f"{MODULE}.InterviewQuestionResponse") as mock_responses,
        patch(f"{MODULE}.log") as mock_log,
    ):
        mock_responses.objects.filter.side_effect = AttributeError("no responses")

        result = score_interviews([(interview, TRIGGER_CODE)])

        assert mock_responses.mock_calls == [READ_RESPONSES[0]]
        assert mock_log.mock_calls == [
            call.warning("could not read responses for interviews [(7, '55758-7')]: no responses")
        ]
        assert interview.mock_calls == []
        assert result == {(7, TRIGGER_CODE): None}
