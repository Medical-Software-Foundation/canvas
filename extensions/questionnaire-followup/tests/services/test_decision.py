"""Tests for the shared decision service, and specifically for what it explains.

``owed_forms`` already runs under the handler's tests, which assert on the effects
it produces. These assert on the *trace* - the sentence the admin diagnostic shows
when a pairing is configured, the patient was screened, and nothing appeared.

That trace is the only account anyone gets of a negative decision (the handler logs
only when it presents something), so each gate is checked for the outcome it
reports as well as the fact that it stopped. These run against the test database
for the same reason the handler's do: a mocked queryset never resolves a field
name.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from canvas_sdk.test_utils.factories import PatientFactory
from canvas_sdk.v1.data import Questionnaire
from canvas_sdk.v1.data.questionnaire import Interview

from questionnaire_followup.services.config_store import new_rule
from questionnaire_followup.services.decision import (
    OUTCOME_ALREADY_ANSWERED,
    OUTCOME_CODE_NOT_FOUND,
    OUTCOME_NO_SCREEN,
    OUTCOME_OWED,
    OUTCOME_SCORE_DID_NOT_FIRE,
    OUTCOME_SCREEN_TOO_OLD,
    Trace,
    already_answered,
    owed_forms,
)

TRIGGER_CODE = "55758-7"
FOLLOWUP_CODE = "44249-1"

# The factory fixtures from conftest.py.
MakeQuestionnaire = Callable[..., Questionnaire]
MakeInterview = Callable[..., Interview]


def _rule(**overrides: Any) -> dict[str, Any]:
    fields = {
        "enabled": True,
        "name": "Depression",
        "trigger_code": TRIGGER_CODE,
        "followup_code": FOLLOWUP_CODE,
    }
    return new_rule(**{**fields, **overrides})


def _trace_one(rules: list[dict[str, Any]], patient_id: str) -> dict[str, Any]:
    """Run the decision for one rule and return its single trace entry."""
    trace: Trace = []
    owed_forms(rules, str(patient_id), datetime.now(UTC), trace)
    assert len(trace) == 1
    return trace[0]


def test_no_screen_on_file_says_so(make_questionnaire: MakeQuestionnaire) -> None:
    """The commonest case of all: this patient was simply never screened."""
    patient = PatientFactory.create()
    make_questionnaire(TRIGGER_CODE, "PHQ-2")
    make_questionnaire(FOLLOWUP_CODE, "PHQ-9")

    entry = _trace_one([_rule()], patient.id)

    assert entry["outcome"] == OUTCOME_NO_SCREEN
    assert entry["rule"] == "Depression"
    assert entry["condition"] == "scores at least 3"
    assert "no committed response to 55758-7" in entry["detail"]


def test_a_screen_outside_one_rule_s_lookback_names_the_window(
    make_questionnaire: MakeQuestionnaire, make_interview: MakeInterview
) -> None:
    """A screen a shorter rule cannot use is reported as out of range, not as absent.

    The screen query is bounded by the LONGEST lookback among the rules, so this
    gate only separates rules from each other: a 40-day-old screen is inside a
    90-day rule and outside a 30-day one. Past every rule's lookback the screen is
    never fetched at all and reads as absent, which is the same answer in
    different words.
    """
    patient = PatientFactory.create()
    trigger = make_questionnaire(TRIGGER_CODE, "PHQ-2")
    make_questionnaire(FOLLOWUP_CODE, "PHQ-9")
    make_interview(patient, trigger, ["2", "2"], age_days=40)

    trace: Trace = []
    owed_forms(
        [
            _rule(name="Wide", trigger_lookback_days=90),
            _rule(name="Narrow", trigger_lookback_days=30),
        ],
        str(patient.id),
        datetime.now(UTC),
        trace,
    )

    narrow = next(entry for entry in trace if entry["rule"] == "Narrow")
    assert narrow["outcome"] == OUTCOME_SCREEN_TOO_OLD
    assert "outside this rule's 30-day lookback" in narrow["detail"]


def test_a_screen_below_the_threshold_reports_the_score(
    make_questionnaire: MakeQuestionnaire, make_interview: MakeInterview
) -> None:
    """The score and the condition it failed, so an operator can see which is wrong."""
    patient = PatientFactory.create()
    trigger = make_questionnaire(TRIGGER_CODE, "PHQ-2")
    make_questionnaire(FOLLOWUP_CODE, "PHQ-9")
    make_interview(patient, trigger, ["1", "1"])

    entry = _trace_one([_rule(threshold=3)], patient.id)

    assert entry["outcome"] == OUTCOME_SCORE_DID_NOT_FIRE
    assert "scored 2" in entry["detail"]
    assert "scores at least 3" in entry["detail"]


def test_an_unscoreable_screen_is_distinguished_from_a_low_one(
    make_questionnaire: MakeQuestionnaire, make_interview: MakeInterview
) -> None:
    """ "Did not score" and "scored 0" are different problems and must read differently.

    This is the failure that looks like nothing at all from the outside: the
    interview is committed and on the chart, but nothing numeric was recorded, so
    the sum is None and no scored comparator can fire.
    """
    patient = PatientFactory.create()
    trigger = make_questionnaire(TRIGGER_CODE, "PHQ-2")
    make_questionnaire(FOLLOWUP_CODE, "PHQ-9")
    make_interview(patient, trigger, ["not a number", "nor this"])

    entry = _trace_one([_rule()], patient.id)

    assert entry["outcome"] == OUTCOME_SCORE_DID_NOT_FIRE
    assert "did not score (no numeric answers recorded)" in entry["detail"]


def test_a_code_this_instance_does_not_have_is_named(
    make_questionnaire: MakeQuestionnaire, make_interview: MakeInterview
) -> None:
    """A pairing can look configured and never fire; the trace says which code is missing."""
    patient = PatientFactory.create()
    trigger = make_questionnaire(TRIGGER_CODE, "PHQ-2")
    make_interview(patient, trigger, ["2", "2"])

    entry = _trace_one([_rule(followup_code="no-such-code")], patient.id)

    assert entry["outcome"] == OUTCOME_CODE_NOT_FOUND
    assert "no-such-code" in entry["detail"]


def test_a_followup_answered_since_the_screen_reads_as_done(
    make_questionnaire: MakeQuestionnaire, make_interview: MakeInterview
) -> None:
    """The pairing completed - distinct from the re-ask window below."""
    patient = PatientFactory.create()
    trigger = make_questionnaire(TRIGGER_CODE, "PHQ-2")
    followup = make_questionnaire(FOLLOWUP_CODE, "PHQ-9")
    make_interview(patient, trigger, ["2", "2"], age_days=1)
    make_interview(patient, followup, ["1"])

    entry = _trace_one([_rule()], patient.id)

    assert entry["outcome"] == OUTCOME_ALREADY_ANSWERED
    assert "the pairing is done" in entry["detail"]


def test_a_followup_inside_the_window_names_the_window(
    make_questionnaire: MakeQuestionnaire, make_interview: MakeInterview
) -> None:
    """The answer predates the screen, so only the re-ask window can be suppressing.

    This is the reason an operator is most likely to mistake for a bug: a fresh
    positive screen, and silence.
    """
    patient = PatientFactory.create()
    trigger = make_questionnaire(TRIGGER_CODE, "PHQ-2")
    followup = make_questionnaire(FOLLOWUP_CODE, "PHQ-9")
    make_interview(patient, followup, ["1"], age_days=10)
    make_interview(patient, trigger, ["2", "2"])

    entry = _trace_one([_rule(suppression_days=90)], patient.id)

    assert entry["outcome"] == OUTCOME_ALREADY_ANSWERED
    assert "within this rule's 90-day re-ask window" in entry["detail"]


def test_an_owed_form_is_traced_too(
    make_questionnaire: MakeQuestionnaire, make_interview: MakeInterview
) -> None:
    """A rule that fires reports that it fired, so a silent rule stands out beside it."""
    patient = PatientFactory.create()
    trigger = make_questionnaire(TRIGGER_CODE, "PHQ-2")
    make_questionnaire(FOLLOWUP_CODE, "PHQ-9")
    make_interview(patient, trigger, ["2", "2"])

    entry = _trace_one([_rule()], patient.id)

    assert entry["outcome"] == OUTCOME_OWED
    assert "PHQ-9 is owed" in entry["detail"]


def test_every_rule_is_traced_even_when_they_stop_at_different_gates(
    make_questionnaire: MakeQuestionnaire, make_interview: MakeInterview
) -> None:
    """One entry per rule, whichever gate each one stopped at - never a silent drop.

    The entries come out grouped by gate, because the gates are batched across
    rules rather than run per rule. Putting them back into the order the admin
    edited them in is the caller's job; see ``FollowUpAdminAPI.diagnose``.
    """
    patient = PatientFactory.create()
    trigger = make_questionnaire(TRIGGER_CODE, "PHQ-2")
    make_questionnaire(FOLLOWUP_CODE, "PHQ-9")
    make_questionnaire("69736-7", "GAD-2")
    make_interview(patient, trigger, ["2", "2"])

    trace: Trace = []
    owed_forms(
        [
            _rule(name="Depression"),
            _rule(name="Anxiety", trigger_code="69736-7", followup_code="69737-5"),
            _rule(name="Too strict", threshold=99),
        ],
        str(patient.id),
        datetime.now(UTC),
        trace,
    )

    assert {(entry["rule"], entry["outcome"]) for entry in trace} == {
        ("Depression", OUTCOME_OWED),
        ("Anxiety", OUTCOME_NO_SCREEN),
        ("Too strict", OUTCOME_SCORE_DID_NOT_FIRE),
    }


def test_tracing_is_optional(
    make_questionnaire: MakeQuestionnaire, make_interview: MakeInterview
) -> None:
    """The handler passes no trace, which must decide exactly the same thing."""
    patient = PatientFactory.create()
    trigger = make_questionnaire(TRIGGER_CODE, "PHQ-2")
    make_questionnaire(FOLLOWUP_CODE, "PHQ-9")
    make_interview(patient, trigger, ["2", "2"])

    traced: Trace = []
    with_trace = owed_forms([_rule()], str(patient.id), datetime.now(UTC), traced)
    without = owed_forms([_rule()], str(patient.id), datetime.now(UTC))

    assert [rule["name"] for rule, _, _ in with_trace] == ["Depression"]
    assert [rule["name"] for rule, _, _ in without] == ["Depression"]
    assert len(traced) == 1


def test_a_patient_who_never_answered_the_followup_is_not_suppressed() -> None:
    """``already_answered`` reads a missing answer as "still owed", never as done."""
    screen = Interview(created=datetime.now(UTC))

    assert already_answered(_rule(), screen, None, datetime.now(UTC)) is False


def test_an_answer_older_than_the_window_stops_suppressing() -> None:
    """The window ends; a rule with no window is settled by the screen date alone."""
    now = datetime.now(UTC)
    screen = Interview(created=now)
    long_ago = now - timedelta(days=120)

    assert already_answered(_rule(suppression_days=90), screen, long_ago, now) is False
    assert already_answered(_rule(suppression_days=0), screen, long_ago, now) is False
