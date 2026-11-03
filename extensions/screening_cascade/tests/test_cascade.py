"""Handler behavior: what gets originated and scored for a committed questionnaire."""

import json
from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from canvas_sdk.effects import EffectType

from screening_cascade.handlers.cascade import ScreeningCascade

MODULE = "screening_cascade.handlers.cascade"
NOTE_UUID = "note-uuid-1"
ON = {"SCREENING_CASCADE_ENABLED": "true"}

PHQ2 = ("LOINC", "58120-7")
PHQ9 = ("LOINC", "44249-1")
GAD2 = ("SNOMED", "836551000000102")


def make_questionnaire(
    coding: tuple[str, str], question_ids: list[int], native: str = ""
) -> MagicMock:
    q = MagicMock()
    q.code_system, q.code = coding
    q.scoring_function_name = native
    q.questions.exclude.return_value.values_list.return_value = question_ids
    return q


def make_interview(questionnaire: MagicMock | None, answers: list[tuple[int, str]]) -> MagicMock:
    interview = MagicMock()
    interview.id = "interview-1"
    interview.committer_id = 7
    interview.entered_in_error_id = None
    interview.patient_id = 11
    interview.note_id = 22
    interview.questionnaires.first.return_value = questionnaire
    interview.interview_responses.filter.return_value.values_list.return_value = answers
    return interview


def make_handler(secrets: dict, context: dict | None = None) -> ScreeningCascade:
    event = SimpleNamespace(
        target=SimpleNamespace(id="command-1"),
        context={"note": {"uuid": NOTE_UUID}} if context is None else context,
    )
    return ScreeningCascade(event=event, secrets=secrets)  # type: ignore[arg-type]


@pytest.fixture
def db() -> Iterator[SimpleNamespace]:
    """Patch every ORM entry point and the command class the handler uses."""
    with (
        patch(f"{MODULE}.Command") as command_cls,
        patch(f"{MODULE}.Questionnaire") as questionnaire_cls,
        patch(f"{MODULE}.Interview") as interview_cls,
        patch(f"{MODULE}.Note") as note_cls,
        patch(f"{MODULE}.QuestionnaireCommand") as qcmd_cls,
    ):
        target = MagicMock()
        target.id = "phq9-uuid"
        target.name = "PHQ-9"
        questionnaire_cls.objects.filter.return_value.order_by.return_value.first.return_value = (
            target
        )
        interview_cls.objects.filter.return_value.filter.return_value.exclude.return_value.exists.return_value = False
        qcmd_cls.return_value.originate.return_value = "ORIGINATE_EFFECT"
        yield SimpleNamespace(
            command=command_cls,
            questionnaire=questionnaire_cls,
            interview=interview_cls,
            note=note_cls,
            qcmd=qcmd_cls,
            target=target,
        )


def commit(db: SimpleNamespace, interview: MagicMock) -> None:
    db.command.objects.get.return_value.anchor_object = interview


def recently_given(db: SimpleNamespace, value: bool) -> None:
    db.interview.objects.filter.return_value.filter.return_value.exclude.return_value.exists.return_value = value


def test_off_by_default_does_nothing(db: SimpleNamespace) -> None:
    assert make_handler({}).compute() == []
    db.command.objects.get.assert_not_called()


def test_invalid_rules_override_fails_closed(db: SimpleNamespace) -> None:
    secrets = {**ON, "SCREENING_CASCADE_RULES": "not json"}
    assert make_handler(secrets).compute() == []
    db.command.objects.get.assert_not_called()


def test_positive_phq2_originates_phq9_on_same_note(db: SimpleNamespace) -> None:
    commit(
        db, make_interview(make_questionnaire(PHQ2, [1, 2], native="phq2"), [(1, "2"), (2, "1")])
    )

    effects = make_handler(ON).compute()

    assert effects == ["ORIGINATE_EFFECT"]
    db.qcmd.assert_called_once_with(note_uuid=NOTE_UUID, questionnaire_id="phq9-uuid")
    db.questionnaire.objects.filter.assert_called_once_with(
        code_system="LOINC", code="44249-1", can_originate_in_charting=True, status="AC"
    )


def test_negative_phq2_originates_nothing(db: SimpleNamespace) -> None:
    commit(
        db, make_interview(make_questionnaire(PHQ2, [1, 2], native="phq2"), [(1, "1"), (2, "1")])
    )
    assert make_handler(ON).compute() == []
    db.qcmd.assert_not_called()


def test_partially_answered_screener_originates_nothing(db: SimpleNamespace) -> None:
    commit(db, make_interview(make_questionnaire(PHQ2, [1, 2]), [(1, "3")]))
    assert make_handler(ON).compute() == []
    db.qcmd.assert_not_called()


def test_unrelated_questionnaire_is_ignored(db: SimpleNamespace) -> None:
    commit(db, make_interview(make_questionnaire(("LOINC", "00000-0"), [1]), [(1, "9")]))
    assert make_handler(ON).compute() == []


def test_uncommitted_or_entered_in_error_interview_is_ignored(db: SimpleNamespace) -> None:
    interview = make_interview(make_questionnaire(PHQ2, [1, 2]), [(1, "3"), (2, "3")])
    interview.entered_in_error_id = 5
    commit(db, interview)
    assert make_handler(ON).compute() == []
    interview.entered_in_error_id = None
    interview.committer_id = None
    assert make_handler(ON).compute() == []


def test_cooldown_blocks_second_follow_up(db: SimpleNamespace) -> None:
    commit(
        db, make_interview(make_questionnaire(PHQ2, [1, 2], native="phq2"), [(1, "3"), (2, "3")])
    )
    recently_given(db, True)
    assert make_handler(ON).compute() == []
    db.qcmd.assert_not_called()


def test_missing_follow_up_questionnaire_logs_and_skips(db: SimpleNamespace) -> None:
    commit(
        db, make_interview(make_questionnaire(PHQ2, [1, 2], native="phq2"), [(1, "3"), (2, "3")])
    )
    db.questionnaire.objects.filter.return_value.order_by.return_value.first.return_value = None
    assert make_handler(ON).compute() == []


def test_no_note_in_context_skips_origination(db: SimpleNamespace) -> None:
    commit(
        db, make_interview(make_questionnaire(PHQ2, [1, 2], native="phq2"), [(1, "3"), (2, "3")])
    )
    assert make_handler(ON, context={}).compute() == []


def test_writes_score_when_canvas_does_not_score_it(db: SimpleNamespace) -> None:
    commit(db, make_interview(make_questionnaire(GAD2, [1, 2]), [(1, "2"), (2, "2")]))

    effects = make_handler(ON).compute()

    assert len(effects) == 2
    result, originate = effects
    assert result.type == EffectType.CREATE_QUESTIONNAIRE_RESULT
    payload = json.loads(result.payload)["data"]
    assert payload == {
        "interview_id": "interview-1",
        "score": 4.0,
        "abnormal": True,
        "narrative": "Score: 4. Positive screen, GAD-7 recommended.",
        "code_system": "INTERNAL",
        "code": "screening_cascade_gad2",
    }
    assert originate == "ORIGINATE_EFFECT"


def test_negative_screen_result_is_not_abnormal(db: SimpleNamespace) -> None:
    commit(db, make_interview(make_questionnaire(GAD2, [1, 2]), [(1, "0"), (2, "1")]))
    (result,) = make_handler(ON).compute()
    payload = json.loads(result.payload)["data"]
    assert payload["abnormal"] is False
    assert payload["narrative"] == "Score: 1. Negative screen."


def test_skips_result_when_canvas_already_scores_it(db: SimpleNamespace) -> None:
    commit(
        db, make_interview(make_questionnaire(PHQ2, [1, 2], native="phq2"), [(1, "0"), (2, "0")])
    )
    assert make_handler(ON).compute() == []


def madrs_rules(**extra: object) -> dict:
    rule = {
        "name": "PHQ-9 to MADRS or HAMD",
        "trigger": {"code_system": "LOINC", "code": "44249-1"},
        "operator": "<=",
        "threshold": 20,
        "follow_up": {"code_system": "INTERNAL", "code": "MADRS"},
        "follow_up_by_staff": {
            "aaaa-bbbb": {"code_system": "INTERNAL", "code": "HAMD"},
        },
        **extra,
    }
    return {**ON, "SCREENING_CASCADE_RULES": json.dumps([rule])}


def nine_answers(value: str) -> list[tuple[int, str]]:
    return [(i, value) for i in range(1, 10)]


def test_clinician_preference_picks_hamd(db: SimpleNamespace) -> None:
    commit(
        db, make_interview(make_questionnaire(PHQ9, list(range(1, 10)), "phq9"), nine_answers("1"))
    )
    db.note.objects.filter.return_value.values_list.return_value.first.return_value = "AAAABBBB"

    effects = make_handler(madrs_rules()).compute()

    assert effects == ["ORIGINATE_EFFECT"]
    db.note.objects.filter.assert_called_once_with(id=NOTE_UUID)
    db.questionnaire.objects.filter.assert_called_once_with(
        code_system="INTERNAL", code="HAMD", can_originate_in_charting=True, status="AC"
    )


def test_clinician_without_preference_gets_default(db: SimpleNamespace) -> None:
    commit(
        db, make_interview(make_questionnaire(PHQ9, list(range(1, 10)), "phq9"), nine_answers("1"))
    )
    db.note.objects.filter.return_value.values_list.return_value.first.return_value = "other"

    make_handler(madrs_rules()).compute()

    db.questionnaire.objects.filter.assert_called_once_with(
        code_system="INTERNAL", code="MADRS", can_originate_in_charting=True, status="AC"
    )


def test_phq9_above_threshold_originates_nothing(db: SimpleNamespace) -> None:
    commit(
        db, make_interview(make_questionnaire(PHQ9, list(range(1, 10)), "phq9"), nine_answers("3"))
    )
    assert make_handler(madrs_rules()).compute() == []


def test_two_rules_same_follow_up_originate_once(db: SimpleNamespace) -> None:
    rule = {
        "trigger": {"code_system": "LOINC", "code": "58120-7"},
        "operator": ">=",
        "threshold": 3,
        "follow_up": {"code_system": "LOINC", "code": "44249-1"},
    }
    secrets = {**ON, "SCREENING_CASCADE_RULES": json.dumps([rule, rule])}
    commit(db, make_interview(make_questionnaire(PHQ2, [1, 2], "phq2"), [(1, "3"), (2, "3")]))
    assert make_handler(secrets).compute() == ["ORIGINATE_EFFECT"]


def test_cooldown_query_scopes_to_patient_and_follow_up(db: SimpleNamespace) -> None:
    commit(
        db, make_interview(make_questionnaire(PHQ2, [1, 2], native="phq2"), [(1, "3"), (2, "3")])
    )
    make_handler(ON).compute()
    db.interview.objects.filter.assert_called_once_with(
        patient_id=11,
        questionnaires__code_system="LOINC",
        questionnaires__code="44249-1",
        entered_in_error__isnull=True,
        deleted=False,
    )
    db.interview.objects.filter.return_value.filter.return_value.exclude.assert_called_once_with(
        id="interview-1"
    )


def test_two_rules_same_result_coding_write_one_result(db: SimpleNamespace) -> None:
    rule = {
        "trigger": {"code_system": "SNOMED", "code": "836551000000102"},
        "operator": ">=",
        "threshold": 3,
        "follow_up": {"code_system": "LOINC", "code": "69737-5"},
        "result": {"code_system": "INTERNAL", "code": "gad2_score"},
    }
    secrets = {**ON, "SCREENING_CASCADE_RULES": json.dumps([rule, rule])}
    commit(db, make_interview(make_questionnaire(GAD2, [1, 2]), [(1, "2"), (2, "2")]))

    effects = make_handler(secrets).compute()

    results = [e for e in effects if e != "ORIGINATE_EFFECT"]
    assert len(results) == 1
    assert effects.count("ORIGINATE_EFFECT") == 1
