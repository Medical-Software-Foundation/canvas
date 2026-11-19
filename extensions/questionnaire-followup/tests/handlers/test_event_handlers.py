"""Tests for the portal follow-up handler.

The handler's queries are the thing most likely to change, so the tests that
exercise them run against the test database rather than a mocked ORM - a mocked
queryset never resolves a field name, and cannot count queries. The query-count
tests exclude ``load_config``, which is monkeypatched (the custom-data table does
not exist in the test database); in production it adds one keyed read.
"""

import json
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock, Mock, call, patch

import pytest
from canvas_sdk.effects import Effect, EffectType
from canvas_sdk.events import EventType
from canvas_sdk.test_utils.factories import NoteFactory, PatientFactory
from canvas_sdk.v1.data import CurrentNoteStateEvent, Note, Patient, Questionnaire
from canvas_sdk.v1.data.note import NoteStates
from canvas_sdk.v1.data.questionnaire import Interview
from pytest_django import DjangoAssertNumQueries

from questionnaire_followup.handlers import event_handlers
from questionnaire_followup.handlers.event_handlers import PortalFollowUpForms
from questionnaire_followup.services.config_store import new_rule

TRIGGER_CODE = "55758-7"
FOLLOWUP_CODE = "44249-1"
MODULE = "questionnaire_followup.handlers.event_handlers"

# The factory fixtures from conftest.py.
MakeQuestionnaire = Callable[..., Questionnaire]
MakeInterview = Callable[..., Interview]


def _handler(
    patient_id: str, rules: list[dict], monkeypatch: pytest.MonkeyPatch
) -> PortalFollowUpForms:
    event = Mock()
    event.type = EventType.PATIENT_PORTAL__GET_FORMS
    event.target.id = str(patient_id)
    monkeypatch.setattr(event_handlers, "load_config", lambda: {"rules": rules})
    return PortalFollowUpForms(event=event)


def _rule(**overrides: Any) -> dict:
    fields = {"enabled": True, "trigger_code": TRIGGER_CODE, "followup_code": FOLLOWUP_CODE}
    return new_rule(**{**fields, **overrides})


def test_positive_screen_assigns_the_followup(
    make_questionnaire: MakeQuestionnaire,
    make_interview: MakeInterview,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A PHQ-2 of 4 with threshold 3 puts the PHQ-9 in front of the patient."""
    patient = PatientFactory.create()
    trigger = make_questionnaire(TRIGGER_CODE, "PHQ-2")
    followup = make_questionnaire(FOLLOWUP_CODE, "PHQ-9")
    make_interview(patient, trigger, ["2", "2"])

    effects = _handler(patient.id, [_rule()], monkeypatch).compute()

    assert len(effects) == 1
    assert effects[0].type == EffectType.PATIENT_PORTAL__FORM_RESULT
    assert str(followup.id) in effects[0].payload


def test_negative_screen_assigns_nothing(
    make_questionnaire: MakeQuestionnaire,
    make_interview: MakeInterview,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Below the threshold, the patient is asked for nothing further."""
    patient = PatientFactory.create()
    trigger = make_questionnaire(TRIGGER_CODE, "PHQ-2")
    make_questionnaire(FOLLOWUP_CODE, "PHQ-9")
    make_interview(patient, trigger, ["1", "1"])

    assert _handler(patient.id, [_rule()], monkeypatch).compute() == []


def test_presented_forms_are_logged_once(
    make_questionnaire: MakeQuestionnaire,
    make_interview: MakeInterview,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One line naming the pairing, the follow-up and the note it targets.

    A successful run used to log nothing at all, which made a portal UAT
    impossible to verify from the logs - the silence was indistinguishable from
    the handler never running.
    """
    patient = PatientFactory.create()
    phq2 = make_questionnaire(TRIGGER_CODE, "PHQ-2")
    make_questionnaire(FOLLOWUP_CODE, "PHQ-9")
    gad2 = make_questionnaire("69736-7", "GAD-2")
    make_questionnaire("69737-5", "GAD-7")
    note = _note(patient, NoteStates.NEW)
    make_interview(patient, phq2, ["2", "2"], note_id=note.dbid)
    make_interview(patient, gad2, ["2", "2"], note_id=note.dbid)
    rules = [
        _rule(name="Depression"),
        _rule(name="Anxiety", trigger_code="69736-7", followup_code="69737-5"),
    ]

    with patch(f"{MODULE}.log") as mock_log:
        effects = _handler(patient.id, rules, monkeypatch).compute()

    # Two forms, still exactly one log line - it is after the loop, not inside it.
    assert len(effects) == 2
    assert mock_log.mock_calls == [
        call.info(
            f"questionnaire_followup: presenting 2 form(s) in the portal to patient "
            f"{patient.id}: 'Depression' -> PHQ-9 ({FOLLOWUP_CODE}) into note {note.id}; "
            f"'Anxiety' -> GAD-7 (69737-5) into note {note.id}"
        )
    ]


def test_a_quiet_portal_load_logs_nothing(
    make_questionnaire: MakeQuestionnaire,
    make_interview: MakeInterview,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The handler runs on every portal page load, so the quiet path must stay silent."""
    patient = PatientFactory.create()
    trigger = make_questionnaire(TRIGGER_CODE, "PHQ-2")
    make_questionnaire(FOLLOWUP_CODE, "PHQ-9")
    make_interview(patient, trigger, ["1", "1"])  # below threshold

    with patch(f"{MODULE}.log") as mock_log:
        assert _handler(patient.id, [_rule()], monkeypatch).compute() == []

    assert mock_log.mock_calls == []


def test_a_form_with_no_editable_note_is_logged_as_a_new_note(
    make_questionnaire: MakeQuestionnaire,
    make_interview: MakeInterview,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The log says where the answer will land, including when Canvas must make a note."""
    patient = PatientFactory.create()
    trigger = make_questionnaire(TRIGGER_CODE, "PHQ-2")
    make_questionnaire(FOLLOWUP_CODE, "PHQ-9")
    note = _note(patient, NoteStates.LOCKED)
    make_interview(patient, trigger, ["2", "2"], note_id=note.dbid)

    with patch(f"{MODULE}.log") as mock_log:
        _handler(patient.id, [_rule(name="Depression")], monkeypatch).compute()

    assert mock_log.mock_calls == [
        call.info(
            f"questionnaire_followup: presenting 1 form(s) in the portal to patient "
            f"{patient.id}: 'Depression' -> PHQ-9 ({FOLLOWUP_CODE}) into a new note"
        )
    ]


# --------------------------------------------------------------------------- #
#  The score rules, end to end
# --------------------------------------------------------------------------- #


def test_a_low_score_fires_an_at_most_rule(
    make_questionnaire: MakeQuestionnaire,
    make_interview: MakeInterview,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Instruments where a LOW score is the concerning one (Mini-Cog, MNA-SF)."""
    patient = PatientFactory.create()
    trigger = make_questionnaire(TRIGGER_CODE, "Mini-Cog")
    followup = make_questionnaire(FOLLOWUP_CODE, "Full cognitive assessment")
    make_interview(patient, trigger, ["1", "1"])  # scores 2

    rule = _rule(comparator="at_most", threshold=2)
    effects = _handler(patient.id, [rule], monkeypatch).compute()

    assert len(effects) == 1
    assert str(followup.id) in effects[0].payload


def test_a_high_score_does_not_fire_an_at_most_rule(
    make_questionnaire: MakeQuestionnaire,
    make_interview: MakeInterview,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The inverse of the standard rule really is inverted, not just relabelled."""
    patient = PatientFactory.create()
    trigger = make_questionnaire(TRIGGER_CODE, "Mini-Cog")
    make_questionnaire(FOLLOWUP_CODE, "Full cognitive assessment")
    make_interview(patient, trigger, ["2", "2"])  # scores 4

    assert (
        _handler(patient.id, [_rule(comparator="at_most", threshold=2)], monkeypatch).compute()
        == []
    )


def test_an_unscoreable_screen_does_not_fire_an_at_most_rule(
    make_questionnaire: MakeQuestionnaire,
    make_interview: MakeInterview,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The trap in "at most": an unscoreable screen read as a zero would fire for everyone."""
    patient = PatientFactory.create()
    trigger = make_questionnaire(TRIGGER_CODE, "Free-text screen")
    make_questionnaire(FOLLOWUP_CODE, "Long form")
    make_interview(patient, trigger, ["often", "never"])

    assert (
        _handler(patient.id, [_rule(comparator="at_most", threshold=2)], monkeypatch).compute()
        == []
    )


@pytest.mark.parametrize(
    ("answers", "fires"),
    [
        pytest.param(["3", "3", "3"], False, id="below-the-band"),
        pytest.param(["3", "3", "4"], True, id="low-end"),
        pytest.param(["5", "5", "4"], True, id="high-end"),
        pytest.param(["5", "5", "5"], False, id="above-the-band"),
    ],
)
def test_only_scores_inside_the_band_fire_a_between_rule(
    answers: list[str],
    fires: bool,
    make_questionnaire: MakeQuestionnaire,
    make_interview: MakeInterview,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A severity band: moderate depression gets a different follow-up from severe."""
    patient = PatientFactory.create()
    trigger = make_questionnaire(TRIGGER_CODE, "PHQ-9")
    make_questionnaire(FOLLOWUP_CODE, "Treatment preferences")
    make_interview(patient, trigger, answers)

    rule = _rule(comparator="between", threshold=10, threshold_max=14)
    effects = _handler(patient.id, [rule], monkeypatch).compute()

    assert bool(effects) is fires


def test_a_backwards_band_fires_for_nobody(
    make_questionnaire: MakeQuestionnaire,
    make_interview: MakeInterview,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Typed the wrong way round, the rule is inert - it is not swapped into 10-14."""
    patient = PatientFactory.create()
    trigger = make_questionnaire(TRIGGER_CODE, "PHQ-9")
    make_questionnaire(FOLLOWUP_CODE, "Treatment preferences")
    make_interview(patient, trigger, ["4", "4", "4"])  # scores 12, inside 10-14

    rule = _rule(comparator="between", threshold=14, threshold_max=10)

    assert _handler(patient.id, [rule], monkeypatch).compute() == []


def test_a_completion_rule_fires_on_an_instrument_that_cannot_be_scored(
    make_questionnaire: MakeQuestionnaire,
    make_interview: MakeInterview,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The only way to pair an instrument whose answers are not numeric ordinals."""
    patient = PatientFactory.create()
    trigger = make_questionnaire(TRIGGER_CODE, "Tobacco use")
    followup = make_questionnaire(FOLLOWUP_CODE, "Readiness to quit")
    make_interview(patient, trigger, ["every day", "yes"])

    effects = _handler(patient.id, [_rule(comparator="completed")], monkeypatch).compute()

    assert len(effects) == 1
    assert str(followup.id) in effects[0].payload


def test_a_completion_rule_still_respects_the_lookback(
    make_questionnaire: MakeQuestionnaire,
    make_interview: MakeInterview,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pairing on completion is not pairing forever."""
    patient = PatientFactory.create()
    trigger = make_questionnaire(TRIGGER_CODE, "Tobacco use")
    make_questionnaire(FOLLOWUP_CODE, "Readiness to quit")
    make_interview(patient, trigger, ["every day"], age_days=60)

    rule = _rule(comparator="completed", trigger_lookback_days=30)

    assert _handler(patient.id, [rule], monkeypatch).compute() == []


def test_stale_positive_screen_is_ignored(
    make_questionnaire: MakeQuestionnaire,
    make_interview: MakeInterview,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A positive screen older than the lookback does not start assigning forms."""
    patient = PatientFactory.create()
    trigger = make_questionnaire(TRIGGER_CODE, "PHQ-2")
    make_questionnaire(FOLLOWUP_CODE, "PHQ-9")
    make_interview(patient, trigger, ["2", "2"], age_days=60)

    assert _handler(patient.id, [_rule(trigger_lookback_days=30)], monkeypatch).compute() == []


def test_completed_followup_clears_the_assignment(
    make_questionnaire: MakeQuestionnaire,
    make_interview: MakeInterview,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Once the patient answers the long form, it stops being offered."""
    patient = PatientFactory.create()
    trigger = make_questionnaire(TRIGGER_CODE, "PHQ-2")
    followup = make_questionnaire(FOLLOWUP_CODE, "PHQ-9")
    make_interview(patient, trigger, ["2", "2"], age_days=1)
    make_interview(patient, followup, ["1"] * 9)

    assert _handler(patient.id, [_rule()], monkeypatch).compute() == []


def test_recent_followup_suppresses_a_fresh_positive(
    make_questionnaire: MakeQuestionnaire,
    make_interview: MakeInterview,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A new positive screen does not re-ask a long form completed days ago."""
    patient = PatientFactory.create()
    trigger = make_questionnaire(TRIGGER_CODE, "PHQ-2")
    followup = make_questionnaire(FOLLOWUP_CODE, "PHQ-9")
    make_interview(patient, followup, ["1"] * 9, age_days=10)
    make_interview(patient, trigger, ["2", "2"])  # newer positive screen

    assert _handler(patient.id, [_rule(suppression_days=90)], monkeypatch).compute() == []


def test_suppression_expires(
    make_questionnaire: MakeQuestionnaire,
    make_interview: MakeInterview,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Past the re-ask window, a fresh positive screen assigns the form again."""
    patient = PatientFactory.create()
    trigger = make_questionnaire(TRIGGER_CODE, "PHQ-2")
    followup = make_questionnaire(FOLLOWUP_CODE, "PHQ-9")
    make_interview(patient, followup, ["1"] * 9, age_days=120)
    make_interview(patient, trigger, ["2", "2"])

    assert len(_handler(patient.id, [_rule(suppression_days=90)], monkeypatch).compute()) == 1


def test_unresolvable_code_assigns_nothing(
    make_questionnaire: MakeQuestionnaire,
    make_interview: MakeInterview,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pairing pointing at a code this instance lacks does nothing, quietly."""
    patient = PatientFactory.create()
    trigger = make_questionnaire(TRIGGER_CODE, "PHQ-2")
    make_interview(patient, trigger, ["2", "2"])  # no follow-up questionnaire exists

    assert _handler(patient.id, [_rule()], monkeypatch).compute() == []


def test_two_rules_sharing_a_followup_assign_it_once(
    make_questionnaire: MakeQuestionnaire,
    make_interview: MakeInterview,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A long form reached by two pairings is still only asked for once."""
    patient = PatientFactory.create()
    trigger = make_questionnaire(TRIGGER_CODE, "PHQ-2")
    other_trigger = make_questionnaire("99999-9", "Broad intake")
    make_questionnaire(FOLLOWUP_CODE, "PHQ-9")
    make_interview(patient, trigger, ["2", "2"])
    make_interview(patient, other_trigger, ["4"])

    rules = [_rule(), _rule(trigger_code="99999-9")]

    assert len(_handler(patient.id, rules, monkeypatch).compute()) == 1


def test_no_rules_means_no_work(monkeypatch: pytest.MonkeyPatch) -> None:
    """With nothing configured the handler returns immediately."""
    patient = PatientFactory.create()

    assert _handler(patient.id, [], monkeypatch).compute() == []


def test_handler_event_configuration() -> None:
    """The handler is wired to the portal's form-selection event."""
    assert PortalFollowUpForms.RESPONDS_TO == EventType.Name(EventType.PATIENT_PORTAL__GET_FORMS)


def test_missing_patient_id_returns_nothing() -> None:
    """With no patient on the event, config is never even read."""
    event = MagicMock()
    event.target.id = ""

    with patch(f"{MODULE}.load_config") as mock_load_config:
        effects = PortalFollowUpForms(event=event).compute()

        assert mock_load_config.mock_calls == []
        assert event.mock_calls == []
        assert effects == []


def _form(effect: Effect) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(effect.payload)["data"]
    return data


def _note(patient: Patient, state: str | None) -> Note:
    """A note for `patient`, with `state` as its current state (None: no state row).

    In the SQLite test database the current-state view is a plain table, and
    NoteFactory only writes the underlying state-change event, so the current
    state is seeded directly.
    """
    note = NoteFactory.create(patient=patient)
    if state is not None:
        CurrentNoteStateEvent.objects.create(note=note, state=state)
    return note


# --------------------------------------------------------------------------- #
#  Which note the follow-up lands in
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("state", "joins_the_screening_note"),
    [
        pytest.param(NoteStates.NEW, True, id="new"),
        pytest.param(NoteStates.UNLOCKED, True, id="unlocked"),
        pytest.param(NoteStates.LOCKED, False, id="locked"),
        pytest.param(NoteStates.SIGNED, False, id="signed"),
        pytest.param(None, False, id="no-state"),
    ],
)
def test_followup_joins_the_screening_note_only_while_it_is_editable(
    state: str | None,
    joins_the_screening_note: bool,
    make_questionnaire: MakeQuestionnaire,
    make_interview: MakeInterview,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Before the visit ends the follow-up joins that note; after, Canvas makes a new one."""
    patient = PatientFactory.create()
    trigger = make_questionnaire(TRIGGER_CODE, "PHQ-2")
    make_questionnaire(FOLLOWUP_CODE, "PHQ-9")
    note = _note(patient, state)
    make_interview(patient, trigger, ["2", "2"], note_id=note.dbid)

    effects = _handler(patient.id, [_rule()], monkeypatch).compute()

    assert len(effects) == 1
    assert _form(effects[0])["note_id"] == (str(note.id) if joins_the_screening_note else None)


def test_followup_that_cannot_originate_in_charting_is_still_assigned_with_a_warning(
    make_questionnaire: MakeQuestionnaire,
    make_interview: MakeInterview,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A follow-up not enabled for charting is still shown, and the gap is logged."""
    patient = PatientFactory.create()
    trigger = make_questionnaire(TRIGGER_CODE, "PHQ-2")
    followup = make_questionnaire(FOLLOWUP_CODE, "PHQ-9", can_originate=False)
    make_interview(patient, trigger, ["2", "2"])

    with patch(f"{MODULE}.log") as mock_log:
        effects = _handler(patient.id, [_rule()], monkeypatch).compute()

        assert mock_log.mock_calls == [
            call.warning(
                "questionnaire_followup: 'PHQ-9' (code=44249-1) is not enabled to originate "
                "in charting; the portal response may not commit into a note"
            ),
            call.info(
                f"questionnaire_followup: presenting 1 form(s) in the portal to patient "
                f"{patient.id}: 'New pairing' -> PHQ-9 ({FOLLOWUP_CODE}) into a new note"
            ),
        ]
        assert [_form(e)["questionnaire_id"] for e in effects] == [str(followup.id)]


# --------------------------------------------------------------------------- #
#  Batching across rules keeps each rule's own settings
# --------------------------------------------------------------------------- #


def test_rules_sharing_a_trigger_each_apply_their_own_lookback(
    make_questionnaire: MakeQuestionnaire,
    make_interview: MakeInterview,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One screen feeds both rules, but only the rule whose lookback reaches it fires."""
    patient = PatientFactory.create()
    trigger = make_questionnaire(TRIGGER_CODE, "PHQ-2")
    wide = make_questionnaire(FOLLOWUP_CODE, "PHQ-9")
    make_questionnaire("11111-1", "Other long form")
    make_interview(patient, trigger, ["2", "2"], age_days=20)

    rules = [
        _rule(trigger_lookback_days=30),
        _rule(followup_code="11111-1", trigger_lookback_days=10),
    ]
    effects = _handler(patient.id, rules, monkeypatch).compute()

    assert [_form(e)["questionnaire_id"] for e in effects] == [str(wide.id)]


def test_zero_suppression_counts_only_answers_since_the_screen(
    make_questionnaire: MakeQuestionnaire,
    make_interview: MakeInterview,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no re-ask window, a long form answered before this screen does not suppress it."""
    patient = PatientFactory.create()
    trigger = make_questionnaire(TRIGGER_CODE, "PHQ-2")
    followup = make_questionnaire(FOLLOWUP_CODE, "PHQ-9")
    make_interview(patient, followup, ["1"] * 9, age_days=5)
    make_interview(patient, trigger, ["2", "2"], age_days=1)

    effects = _handler(patient.id, [_rule(suppression_days=0)], monkeypatch).compute()

    assert [_form(e)["questionnaire_id"] for e in effects] == [str(followup.id)]


def test_one_rules_answer_does_not_settle_another_rule(
    make_questionnaire: MakeQuestionnaire,
    make_interview: MakeInterview,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Answering one pairing's long form leaves a different pairing still owed."""
    patient = PatientFactory.create()
    phq2 = make_questionnaire(TRIGGER_CODE, "PHQ-2")
    phq9 = make_questionnaire(FOLLOWUP_CODE, "PHQ-9")
    gad2 = make_questionnaire("69736-7", "GAD-2")
    gad7 = make_questionnaire("69737-5", "GAD-7")
    make_interview(patient, phq2, ["2", "2"], age_days=2)
    make_interview(patient, gad2, ["2", "2"], age_days=2)
    make_interview(patient, phq9, ["1"] * 9, age_days=1)  # depression pairing done

    rules = [_rule(), _rule(trigger_code="69736-7", followup_code="69737-5")]
    effects = _handler(patient.id, rules, monkeypatch).compute()

    assert [_form(e)["questionnaire_id"] for e in effects] == [str(gad7.id)]


def test_ambiguous_followup_code_assigns_nothing(
    make_questionnaire: MakeQuestionnaire,
    make_interview: MakeInterview,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two active questionnaires sharing the follow-up code are not guessed between."""
    patient = PatientFactory.create()
    trigger = make_questionnaire(TRIGGER_CODE, "PHQ-2")
    make_questionnaire(FOLLOWUP_CODE, "PHQ-9")
    make_questionnaire(FOLLOWUP_CODE, "PHQ-9 (copy)")
    make_interview(patient, trigger, ["2", "2"])

    with patch("questionnaire_followup.services.questionnaires.log") as mock_log:
        effects = _handler(patient.id, [_rule()], monkeypatch).compute()

        assert mock_log.mock_calls == [
            call.warning(
                "questionnaire code=44249-1 matches multiple active questionnaires; "
                "refusing to guess which one a pairing meant"
            )
        ]
        assert effects == []


# --------------------------------------------------------------------------- #
#  Query budget - this handler runs on every portal page load
# --------------------------------------------------------------------------- #


def _pairings(
    count: int, make_questionnaire: MakeQuestionnaire
) -> list[tuple[dict[str, Any], Questionnaire]]:
    pairings = []
    for i in range(count):
        trigger = make_questionnaire(f"T-{i}", f"Short {i}")
        make_questionnaire(f"F-{i}", f"Long {i}")
        pairings.append((_rule(trigger_code=f"T-{i}", followup_code=f"F-{i}"), trigger))
    return pairings


@pytest.mark.parametrize("rule_count", [1, 10])
def test_patient_with_no_recent_screen_costs_one_query(
    rule_count: int,
    make_questionnaire: MakeQuestionnaire,
    monkeypatch: pytest.MonkeyPatch,
    django_assert_num_queries: DjangoAssertNumQueries,
) -> None:
    """The common case ends after one patient-scoped query, however many pairings exist."""
    patient = PatientFactory.create()
    rules = [rule for rule, _ in _pairings(rule_count, make_questionnaire)]
    handler = _handler(patient.id, rules, monkeypatch)

    with django_assert_num_queries(1):
        assert handler.compute() == []


@pytest.mark.parametrize("rule_count", [1, 10])
def test_owed_forms_cost_a_fixed_number_of_queries(
    rule_count: int,
    make_questionnaire: MakeQuestionnaire,
    make_interview: MakeInterview,
    monkeypatch: pytest.MonkeyPatch,
    django_assert_num_queries: DjangoAssertNumQueries,
) -> None:
    """Screens, scores, questionnaires, follow-ups, note states, note ids: six, for any N."""
    patient = PatientFactory.create()
    pairings = _pairings(rule_count, make_questionnaire)
    for _rule_, trigger in pairings:
        note = _note(patient, NoteStates.NEW)
        make_interview(patient, trigger, ["2", "2"], note_id=note.dbid)
    handler = _handler(patient.id, [rule for rule, _ in pairings], monkeypatch)

    with django_assert_num_queries(6):
        effects = handler.compute()

    assert len(effects) == rule_count
    assert all(_form(e)["note_id"] for e in effects)


@pytest.mark.parametrize("rule_count", [1, 10])
def test_completion_rules_skip_the_scoring_query(
    rule_count: int,
    make_questionnaire: MakeQuestionnaire,
    make_interview: MakeInterview,
    monkeypatch: pytest.MonkeyPatch,
    django_assert_num_queries: DjangoAssertNumQueries,
) -> None:
    """No rule reads a score, so the responses are never read: five, not six."""
    patient = PatientFactory.create()
    pairings = _pairings(rule_count, make_questionnaire)
    rules = []
    for rule, trigger in pairings:
        note = _note(patient, NoteStates.NEW)
        make_interview(patient, trigger, ["2", "2"], note_id=note.dbid)
        rules.append({**rule, "comparator": "completed"})
    handler = _handler(patient.id, rules, monkeypatch)

    with django_assert_num_queries(5):
        effects = handler.compute()

    assert len(effects) == rule_count
