import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from canvas_generated.messages.effects_pb2 import EffectType
from canvas_sdk.events import EventType

from charting_tools.api.templates_api import prepare_rule, validate_payload
from charting_tools.handlers.rule_engine import RuleEngine, card_key
from charting_tools.rules import (
    NoteState,
    clean_rule,
    condition_met,
    read_answers,
    rule_met,
    score,
    watched_commands,
)
from tests.conftest import make_template, payload

NOTE_ID = "3f2b8a1c9d4e4f60a7b8c9d0e1f2a3b4"
PHQ2 = {"code_system": "LOINC", "code": "55757-9", "name": "PHQ-2", "schema_key": "questionnaire"}


def phq2_data(first: int | None, second: int | None) -> dict:
    """A staged PHQ-2 command's data, as home-app stores it: option pks per question."""
    options = [{"pk": 10 + v, "code": f"LA{v}", "value": str(v), "label": str(v)} for v in range(4)]
    data = {
        "questionnaire": {
            "value": 77,
            "extra": {
                "questions": [
                    {"pk": 1, "name": "question-1", "type": "SING", "coding": {"system": "LOINC", "code": "44250-9"}, "options": options},
                    {"pk": 2, "name": "question-2", "type": "SING", "coding": {"system": "LOINC", "code": "44255-8"}, "options": options},
                ]
            },
        }
    }
    if first is not None:
        data["question-1"] = 10 + first
    if second is not None:
        data["question-2"] = 10 + second
    return data


# ── Reading staged answers ───────────────────────────────────────────


def test_read_answers_and_score() -> None:
    answers = read_answers(phq2_data(2, 1))
    assert answers["LOINC|44250-9"] == {"options": [("LA2", 2.0)], "number": None}
    assert score(answers) == 3.0
    assert read_answers(phq2_data(None, None)) == {}


def test_read_multiple_choice_counts_only_selected() -> None:
    data = {
        "questionnaire": {"extra": {"questions": [{
            "pk": 5, "name": "question-5", "type": "MULT", "coding": {"system": "S", "code": "sx"},
            "options": [{"pk": 50, "code": "a", "value": "1"}, {"pk": 51, "code": "b", "value": "2"}],
        }]}},
        "question-5": [{"value": 50, "selected": True}, {"value": 51, "selected": False}],
    }
    assert read_answers(data)["S|sx"]["options"] == [("a", 1.0)]


# ── Conditions ──────────────────────────────────────────────────────


class FakeState(NoteState):
    def __init__(self, diagnoses: set[str] | None = None, commands: list | None = None) -> None:
        self._diagnoses = diagnoses or set()
        self._questionnaire_commands = commands or []
        self._versions = {("LOINC", "55757-9"): {77}}


def test_score_condition_on_staged_phq2() -> None:
    positive = {"type": "score", "questionnaire": PHQ2, "op": ">=", "value": 3}
    assert condition_met(positive, FakeState(commands=[phq2_data(2, 1)]))
    assert not condition_met(positive, FakeState(commands=[phq2_data(1, 1)]))
    # A different questionnaire version id isn't this PHQ-2.
    other = phq2_data(3, 3)
    other["questionnaire"]["value"] = 999
    assert not condition_met(positive, FakeState(commands=[other]))


def test_answer_and_diagnosis_conditions() -> None:
    answer = {"type": "answer", "questionnaire": PHQ2, "question": {"key": "LOINC|44250-9"}, "options": [{"key": "LA3"}]}
    assert condition_met(answer, FakeState(commands=[phq2_data(3, 0)]))
    assert not condition_met(answer, FakeState(commands=[phq2_data(2, 0)]))

    ckd = {"type": "diagnosis", "match_codes": ["N18", "N186"]}
    assert condition_met(ckd, FakeState(diagnoses={"N186", "E119"}))
    assert not condition_met(ckd, FakeState(diagnoses={"E119"}))


def test_all_and_any() -> None:
    conditions = [{"type": "diagnosis", "match_codes": ["N186"]}, {"type": "diagnosis", "match_codes": ["I509"]}]
    state = FakeState(diagnoses={"N186"})
    assert not rule_met({"match": "all", "conditions": conditions}, state)
    assert rule_met({"match": "any", "conditions": conditions}, state)


def test_watched_commands() -> None:
    rule = {"conditions": [{"type": "diagnosis"}, {"type": "score", "questionnaire": {"schema_key": "ros"}}]}
    assert watched_commands(rule) == {"diagnose", "assess", "updateDiagnosis", "assessCodingGap", "ros"}


# ── Saving ──────────────────────────────────────────────────────────


def test_clean_rule_validation() -> None:
    rule, error = clean_rule({
        "match": "any",
        "conditions": [{"type": "score", "questionnaire": PHQ2, "op": ">=", "value": "3"}],
        "action": {"target_id": "t9", "mode": "insert"},
    })
    assert error is None and rule is not None
    assert rule["conditions"][0]["value"] == 3.0 and rule["action"] == {"mode": "insert"}

    for raw, message in [
        ({"conditions": []}, "Add at least one condition"),
        ({"conditions": [{"type": "diagnosis", "sources": []}], "action": {"target_id": "x"}}, "choose at least one diagnosis"),
        ({"conditions": [{"type": "score", "questionnaire": PHQ2, "op": "~", "value": 3}]}, "how to compare"),
        ({"conditions": [{"type": "answer", "questionnaire": PHQ2, "question": {"key": "q"}, "options": []}]}, "at least one answer"),
    ]:
        assert clean_rule(raw)[1] is not None and message in clean_rule(raw)[1]


def test_rule_payload_holds_its_own_commands() -> None:
    rule = {"conditions": [{"type": "score", "questionnaire": PHQ2, "op": ">=", "value": 3}], "action": {}}
    fields, error = validate_payload({
        "kind": "rule", "name": "Positive PHQ-2", "rule": rule,
        "commands": [{"schema_key": "questionnaire", "questionnaire": {"code_system": "LOINC", "code": "44249-1"},
                      "carry_forward": True},
                     {"schema_key": "plan", "fields": {"narrative": "Discuss PHQ-9 results"}}],
    })
    assert error is None and fields is not None
    # A body from before actions existed reads as one suggested add.
    [action] = fields["rule"]["actions"]
    assert action["type"] == "add" and action["mode"] == "suggest"
    assert [c["schema_key"] for c in action["commands"]] == ["questionnaire", "plan"]
    assert action["commands"][0]["carry_forward"] is False  # rules start fresh, like order sets
    assert action["commands"][1]["fields"] == {"narrative": "Discuss PHQ-9 results"}
    assert fields["commands"] == [] and fields["show_in_menu"] is False

    _, error = validate_payload({"kind": "rule", "name": "A", "rule": rule, "commands": []})
    assert error == "Action 1: add at least one command"


def test_rule_actions_parse_update_and_delete() -> None:
    rule = {
        "conditions": [{"type": "score", "questionnaire": PHQ2, "op": ">=", "value": 3}],
        "actions": [
            {"type": "delete", "target": {"schema_key": "questionnaire", "questionnaire": {"code_system": "LOINC", "code": "55757-9", "name": "PHQ-2"}}},
            {"type": "add", "mode": "insert", "commands": [{"schema_key": "questionnaire", "questionnaire": {"code_system": "LOINC", "code": "44249-1"}}]},
            {"type": "update", "target": {"schema_key": "plan"}, "fields": {"narrative": "PHQ-2 positive; PHQ-9 given"}},
        ],
    }
    fields, error = validate_payload({"kind": "rule", "name": "Replace PHQ-2", "rule": rule})
    assert error is None and fields is not None
    actions = fields["rule"]["actions"]
    assert [a["type"] for a in actions] == ["delete", "add", "update"]
    assert actions[0]["target"]["questionnaire"]["code"] == "55757-9"
    assert actions[2]["fields"] == {"narrative": "PHQ-2 positive; PHQ-9 given"}

    for bad, message in [
        ({"type": "update", "target": {"schema_key": "plan"}}, "fill in what to change"),
        ({"type": "delete", "target": {"schema_key": "ros"}}, "choose which questionnaire"),
        ({"type": "delete", "target": {"schema_key": "nope"}}, "choose which command"),
        ({"type": "launch"}, "choose what the action does"),
    ]:
        _, error = validate_payload({"kind": "rule", "name": "A", "rule": {**rule, "actions": [bad]}})
        assert error is not None and message in error, (bad, error)


def test_prepare_rule_expands_diagnoses(mocker: MagicMock) -> None:
    mocker.patch("charting_tools.diagnoses.expand_icd10", return_value=["N18", "N186"])
    rule = {"conditions": [{"type": "diagnosis", "sources": [{"code": "N18", "include_children": True}]}],
            "action": {"mode": "suggest"}}
    assert prepare_rule(rule, {"UMLS_API_KEY": "k"}, None, None) is None
    assert rule["conditions"][0]["match_codes"] == ["N18", "N186"]


# ── Engine ──────────────────────────────────────────────────────────


def _event(event_type: int = EventType.QUESTIONNAIRE_COMMAND__POST_UPDATE) -> SimpleNamespace:
    return SimpleNamespace(type=event_type, name=EventType.Name(event_type),
                           context={"note": {"uuid": NOTE_ID}}, target=SimpleNamespace(id="c1"))


def _rule(mode: str) -> SimpleNamespace:
    return make_template(template_id="r1", kind="rule", name="Positive PHQ-2", rule={
        "match": "all",
        "conditions": [{"type": "score", "questionnaire": PHQ2, "op": ">=", "value": 3}],
        "action": {"target_id": "t9", "mode": mode},
    })


@pytest.fixture
def engine(mocker: MagicMock):  # type: ignore[no-untyped-def]
    module = "charting_tools.handlers.rule_engine"
    note = SimpleNamespace(id=NOTE_ID, dbid=1, patient_id=1, datetime_of_service=None, patient=SimpleNamespace(id="pt1"))
    mocker.patch(f"{module}.Note.objects.select_related").return_value.defer.return_value.filter.return_value.first.return_value = note
    target = make_template(template_id="t9", name="PHQ-9", commands=[{"schema_key": "plan"}])

    def filter_templates(**kwargs: object) -> MagicMock:
        chain = MagicMock()
        chain.order_by.return_value = [env["rule"]]
        chain.first.return_value = target
        return chain

    env = {"rule": _rule("insert"), "met": True, "fired": []}
    mocker.patch(f"{module}.NoteTemplate.objects.filter", side_effect=filter_templates)
    mocker.patch(f"{module}.NoteMetadata.objects.filter").return_value.values_list.side_effect = lambda *a, **k: env["fired"]
    mocker.patch(f"{module}.rule_met", side_effect=lambda spec, state: env["met"])
    mocker.patch("charting_tools.insertion.resolve", return_value={})
    mocker.patch("canvas_sdk.effects.note_metadata.base.Note.objects.filter").return_value.exists.return_value = True
    store: dict = {}
    cache = MagicMock()
    cache.get.side_effect = store.get
    cache.set.side_effect = lambda k, v, timeout_seconds=None: store.__setitem__(k, v)
    cache.get_or_set.side_effect = lambda k, v, timeout_seconds=None: store.setdefault(k, v)
    mocker.patch(f"{module}.get_cache", return_value=cache)
    env["store"] = store
    return env


def test_simultaneous_events_act_once(engine: dict) -> None:
    # Two events before the note marker is saved: only the first claims the rule.
    first = RuleEngine(event=_event()).compute()
    assert [e.type for e in first] == [EffectType.BATCH_ORIGINATE_COMMANDS, EffectType.UPSERT_NOTE_METADATA]
    assert RuleEngine(event=_event()).compute() == []


def test_insert_once_per_note(engine: dict) -> None:
    effects = RuleEngine(event=_event()).compute()
    assert [e.type for e in effects] == [EffectType.BATCH_ORIGINATE_COMMANDS, EffectType.UPSERT_NOTE_METADATA]
    assert payload(effects[1])["data"]["key"] == "charting_tools:rule:r1"

    engine["fired"] = ["charting_tools:rule:r1"]
    assert RuleEngine(event=_event()).compute() == []


def test_rule_adds_its_own_commands(engine: dict) -> None:
    rule = _rule("insert")
    rule.commands = [{"schema_key": "plan", "fields": {"narrative": "Repeat PHQ-9 in 4 weeks"}}]
    engine["rule"] = rule
    effects = RuleEngine(event=_event()).compute()
    command = payload(effects[0])["data"]["commands"][0]
    assert command["type"] == "ORIGINATE_PLAN_COMMAND"
    assert command["data"]["narrative"] == "Repeat PHQ-9 in 4 weeks"


def test_insert_waits_for_conditions(engine: dict) -> None:
    engine["met"] = False
    assert RuleEngine(event=_event()).compute() == []


def test_unrelated_command_skips_rule(engine: dict) -> None:
    assert RuleEngine(event=_event(EventType.DIAGNOSE_COMMAND__POST_UPDATE)).compute() == []


def test_suggest_shows_then_withdraws_card_without_repeating(engine: dict) -> None:
    engine["rule"] = _rule("suggest")
    [card] = RuleEngine(event=_event()).compute()
    assert card.type == EffectType.ADD_OR_UPDATE_PROTOCOL_CARD
    body = payload(card)
    assert body["key"] == card_key("r1") and body["patient"] == "pt1"
    assert body["data"]["status"] == "due"
    assert body["data"]["recommendations"][0]["button"] == "Add"
    assert len(body["data"]["recommendations"][0]["commands"]) == 1

    assert RuleEngine(event=_event()).compute() == []  # unchanged, not re-sent

    engine["met"] = False
    [withdrawn] = RuleEngine(event=_event()).compute()
    assert payload(withdrawn)["data"]["status"] == "not_applicable"


# ── Metadata conditions ──────────────────────────────────────────────


class MetadataState(FakeState):
    def __init__(self, metadata: dict[str, dict[str, str]]) -> None:
        super().__init__()
        self._metadata = metadata


def test_metadata_condition_validation() -> None:
    rule, error = clean_rule({
        "conditions": [{"type": "metadata", "source": "appointment", "key": " visit_reason ", "op": "any_of",
                        "values": ["New patient", " transfer ", ""]}],
        "action": {"target_id": "t9"},
    })
    assert error is None and rule is not None
    assert rule["conditions"][0] == {"type": "metadata", "source": "appointment", "key": "visit_reason",
                                     "op": "any_of", "values": ["New patient", "transfer"]}
    for item, message in [
        ({"type": "metadata", "source": "staff", "key": "k", "op": "equals", "values": ["x"]}, "patient, appointment, or note"),
        ({"type": "metadata", "source": "note", "key": "", "op": "equals", "values": ["x"]}, "key"),
        ({"type": "metadata", "source": "note", "key": "k", "op": "equals", "values": []}, "value to match"),
    ]:
        assert message in (clean_rule({"conditions": [item], "action": {"target_id": "t"}})[1] or "")
    rule, error = clean_rule({"conditions": [{"type": "metadata", "source": "note", "key": "k", "op": "present"}],
                              "action": {"target_id": "t"}})
    assert error is None


@pytest.mark.parametrize(
    ("op", "values", "stored", "expected"),
    [
        ("equals", ["New Patient"], {"visit_reason": " new patient "}, True),
        ("equals", ["new patient"], {"visit_reason": "follow up"}, False),
        ("any_of", ["transfer", "new patient"], {"visit_reason": "Transfer"}, True),
        ("present", [], {"visit_reason": "x"}, True),
        ("present", [], {"visit_reason": "  "}, False),
        ("absent", [], {}, True),
        ("absent", [], {"visit_reason": "x"}, False),
    ],
)
def test_metadata_condition_reads_current_values(op: str, values: list, stored: dict, expected: bool) -> None:
    condition = {"type": "metadata", "source": "appointment", "key": "visit_reason", "op": op, "values": values}
    assert condition_met(condition, MetadataState({"appointment": stored})) is expected


def test_metadata_rules_watch_note_creation_and_their_metadata() -> None:
    watched = watched_commands({"conditions": [{"type": "metadata", "source": "appointment"}]})
    assert watched == {"created", "metadata:appointment"}


def _metadata_rule() -> SimpleNamespace:
    return make_template(template_id="r2", kind="rule", name="New patient intake", rule={
        "match": "all",
        "conditions": [{"type": "metadata", "source": "appointment", "key": "visit_reason", "op": "equals", "values": ["new"]}],
        "action": {"target_id": "t9", "mode": "insert"},
    })


def test_note_created_and_booking_run_metadata_rules(engine: dict, mocker: MagicMock) -> None:
    module = "charting_tools.handlers.rule_engine"
    note = SimpleNamespace(id=NOTE_ID, dbid=1, patient_id=1, datetime_of_service=None, patient=SimpleNamespace(id="pt1"))
    mocker.patch(f"{module}.Note.objects.select_related").return_value.defer.return_value.filter.return_value.first.return_value = note
    mocker.patch(f"{module}.Appointment.objects.select_related").return_value.defer.return_value.filter.return_value.first.return_value = (
        SimpleNamespace(note=note)
    )
    engine["rule"] = _metadata_rule()
    for event_type in (EventType.NOTE_CREATED, EventType.APPOINTMENT_CREATED):
        event = SimpleNamespace(type=event_type, name=EventType.Name(event_type), context={}, target=SimpleNamespace(id="x"))
        engine["store"].clear()  # each case on its own note
        effects = RuleEngine(event=event).compute()
        assert effects[0].type == EffectType.BATCH_ORIGINATE_COMMANDS


def test_note_creation_skips_questionnaire_only_rules(engine: dict) -> None:
    event = SimpleNamespace(type=EventType.NOTE_CREATED, name="NOTE_CREATED", context={}, target=SimpleNamespace(id=NOTE_ID))
    assert RuleEngine(event=event).compute() == []


# ── Update and remove actions ───────────────────────────────────────


def _staged(dbid: int, uuid: str, questionnaire_value: int | None = None) -> SimpleNamespace:
    data = {"questionnaire": {"value": questionnaire_value}} if questionnaire_value is not None else {}
    return SimpleNamespace(dbid=dbid, id=uuid, data=data)


def test_update_and_delete_touch_only_matching_staged_commands(mocker: MagicMock) -> None:
    from charting_tools.handlers.rule_engine import delete_effects, update_effects

    query = mocker.patch("charting_tools.handlers.rule_engine.Command.objects.filter")
    query.return_value.order_by.return_value = [
        _staged(1, "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", 77),
        _staged(2, "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", 999),  # another questionnaire
    ]
    state = FakeState()
    note = SimpleNamespace(id=NOTE_ID, dbid=1, datetime_of_service=None)
    effects = delete_effects({"target": {"schema_key": "questionnaire", "questionnaire": PHQ2}}, note, state)
    kwargs = query.call_args.kwargs
    assert kwargs["state"] == "staged" and kwargs["committer__isnull"] is True  # committed commands are never touched
    assert [e.type for e in effects] == [EffectType.DELETE_QUESTIONNAIRE_COMMAND]
    assert payload(effects[0])["command"] == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

    query.return_value.order_by.return_value = [_staged(3, "cccccccccccccccccccccccccccccccc")]
    [edit] = update_effects({"target": {"schema_key": "plan"}, "fields": {"narrative": "Updated"}}, note, state)
    assert edit.type == EffectType.EDIT_PLAN_COMMAND
    data = payload(edit)["data"]
    # Only what the action sets is sent.
    assert {k: v for k, v in data.items() if k not in ("command_uuid", "note_uuid")} == {"narrative": "Updated"}


def test_rule_runs_actions_in_order_once(engine: dict, mocker: MagicMock) -> None:
    rule = _rule("insert")
    rule.rule = {**rule.rule, "actions": [
        {"type": "delete", "target": {"schema_key": "plan"}},
        {"type": "add", "mode": "insert", "commands": [{"schema_key": "plan", "fields": {"narrative": "New plan"}}]},
    ]}
    engine["rule"] = rule
    mocker.patch("charting_tools.handlers.rule_engine.Command.objects.filter").return_value.order_by.return_value = [
        _staged(4, "dddddddddddddddddddddddddddddddd")
    ]
    effects = RuleEngine(event=_event()).compute()
    assert [e.type for e in effects] == [
        EffectType.DELETE_PLAN_COMMAND, EffectType.BATCH_ORIGINATE_COMMANDS, EffectType.UPSERT_NOTE_METADATA
    ]
    engine["fired"] = ["charting_tools:rule:r1"]
    assert RuleEngine(event=_event()).compute() == []


def test_suggested_adds_go_on_the_card_while_automatic_actions_run(engine: dict, mocker: MagicMock) -> None:
    rule = _rule("suggest")
    rule.rule = {**rule.rule, "actions": [
        {"type": "add", "mode": "suggest", "commands": [{"schema_key": "plan"}]},
        {"type": "delete", "target": {"schema_key": "plan"}},
    ]}
    engine["rule"] = rule
    mocker.patch("charting_tools.handlers.rule_engine.Command.objects.filter").return_value.order_by.return_value = [
        _staged(5, "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee")
    ]
    effects = RuleEngine(event=_event()).compute()
    assert [e.type for e in effects] == [
        EffectType.ADD_OR_UPDATE_PROTOCOL_CARD, EffectType.DELETE_PLAN_COMMAND, EffectType.UPSERT_NOTE_METADATA
    ]


# ── Diagnoses from every diagnosis command ──────────────────────────


def test_note_diagnoses_reads_every_diagnosis_command(mocker: MagicMock) -> None:
    from charting_tools.note_conditions import DIAGNOSIS_COMMANDS, note_diagnoses

    def cmd(schema_key: str, data: dict) -> SimpleNamespace:
        return SimpleNamespace(schema_key=schema_key, data=data)

    gap_pick = {"value": "x", "text": "Hypertensive CKD", "extra": {"coding": [
        {"system": "http://snomed.info/sct", "code": "123"},
        {"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": "I12.0"},
    ]}}
    query = mocker.patch("charting_tools.note_conditions.Command.objects.filter")
    query.return_value.exclude.return_value.order_by.return_value = [
        cmd("diagnose", {"diagnose": {"value": "N18.6", "text": "ESRD"}}),
        cmd("updateDiagnosis", {"conditionId": 4, "newConditionCode": {"value": "N18.5", "text": "CKD 5"}}),
        cmd("updateDiagnosis", {"newConditionCode": "Z99.2"}),
        cmd("assessCodingGap", {"status": "accept and diagnose", "diagnose": [gap_pick]}),
        cmd("assessCodingGap", {"status": "refute", "diagnose": [{"value": "E11.9", "text": "T2DM"}]}),
    ]
    found = note_diagnoses(SimpleNamespace(dbid=1))
    assert [d["code"] for d in found] == ["N186", "N185", "Z992", "I120"]
    assert found[3]["label"] == "Hypertensive CKD"
    assert set(query.call_args.kwargs["schema_key__in"]) == set(DIAGNOSIS_COMMANDS)


def test_diagnosis_rules_watch_change_diagnosis_and_coding_gaps() -> None:
    from charting_tools.handlers.rule_engine import RuleEngine

    watched = watched_commands({"conditions": [{"type": "diagnosis"}]})
    assert {"diagnose", "assess", "updateDiagnosis", "assessCodingGap"} <= watched
    assert "UPDATE_DIAGNOSIS_COMMAND__POST_UPDATE" in RuleEngine.RESPONDS_TO
    assert "ASSESS_CODING_GAP_COMMAND__POST_UPDATE" in RuleEngine.RESPONDS_TO


def test_assess_added_from_the_chart_runs_diagnosis_rules(mocker: MagicMock) -> None:
    """An Assess started from a condition arrives filled in and may never be edited."""
    from charting_tools.note_conditions import note_diagnoses

    assert "ASSESS_COMMAND__POST_ORIGINATE" in RuleEngine.RESPONDS_TO
    assert "ASSESS_COMMAND__POST_INSERTED_INTO_NOTE" in RuleEngine.RESPONDS_TO
    # Not yet readable from the note: the event's own fields count.
    mocker.patch("charting_tools.note_conditions.Command.objects.filter").return_value.exclude.return_value.order_by.return_value = []
    condition = SimpleNamespace(dbid=12, codings=MagicMock())
    condition.codings.all.return_value = [SimpleNamespace(system="ICD-10", code="N18.6", display="ESRD")]
    mocker.patch("charting_tools.note_conditions.Condition.objects.filter").return_value.prefetch_related.return_value = [condition]
    found = note_diagnoses(SimpleNamespace(dbid=1), ("assess", {"condition": {"value": 12, "text": "ESRD"}}))
    assert [d["code"] for d in found] == ["N186"]


# ── Metadata saved after the note exists ────────────────────────────


def _metadata_event(event_type: int, context: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(type=event_type, name=EventType.Name(event_type), context=context or {},
                           target=SimpleNamespace(id="m1"))


@pytest.fixture
def open_note(engine: dict, mocker: MagicMock) -> SimpleNamespace:
    module = "charting_tools.handlers.rule_engine"
    note = SimpleNamespace(id=NOTE_ID, dbid=1, patient_id=1, datetime_of_service=None, patient=SimpleNamespace(id="pt1"))
    mocker.patch(f"{module}.CurrentNoteStateEvent.objects.filter").return_value.exists.return_value = True
    mocker.patch(f"{module}.Note.objects.select_related").return_value.defer.return_value.filter.return_value.first.return_value = note
    engine["rule"] = _metadata_rule()
    return note


def test_appointment_metadata_saved_later_runs_metadata_rules(open_note: SimpleNamespace, mocker: MagicMock) -> None:
    mocker.patch("charting_tools.handlers.rule_engine.Appointment.objects.select_related").return_value.defer.return_value.filter.return_value.first.return_value = (
        SimpleNamespace(note=open_note)
    )
    event = _metadata_event(EventType.APPOINTMENT_METADATA_UPDATED, {"appointment": {"id": "appt1"}})
    effects = RuleEngine(event=event).compute()
    assert effects[0].type == EffectType.BATCH_ORIGINATE_COMMANDS


def test_note_metadata_from_this_plugin_does_not_rerun_rules(open_note: SimpleNamespace, mocker: MagicMock) -> None:
    rows = mocker.patch("charting_tools.handlers.rule_engine.NoteMetadata.objects.filter")
    rows.return_value.values_list.return_value.first.return_value = ("charting_tools:rule:r2", 1)
    assert RuleEngine(event=_metadata_event(EventType.NOTE_METADATA_CREATED)).compute() == []


def test_note_metadata_from_elsewhere_runs_rules(engine: dict, open_note: SimpleNamespace, mocker: MagicMock) -> None:
    rows = mocker.patch("charting_tools.handlers.rule_engine.NoteMetadata.objects.filter")
    rows.return_value.values_list.side_effect = lambda *fields, **kw: (
        MagicMock(first=MagicMock(return_value=("visit_reason", 1))) if fields == ("key", "note_id") else []
    )
    engine["rule"].rule["conditions"][0]["source"] = "note"
    effects = RuleEngine(event=_metadata_event(EventType.NOTE_METADATA_UPDATED)).compute()
    assert effects[0].type == EffectType.BATCH_ORIGINATE_COMMANDS


def test_patient_metadata_rechecks_open_notes(engine: dict, open_note: SimpleNamespace, mocker: MagicMock) -> None:
    notes = mocker.patch("charting_tools.handlers.rule_engine.Note.objects.select_related")
    closed = SimpleNamespace(id="c" * 32, dbid=2, patient_id=1, datetime_of_service=None, patient=SimpleNamespace(id="pt1"))
    notes.return_value.defer.return_value.filter.return_value.order_by.return_value.__getitem__.return_value = [open_note, closed]
    states = mocker.patch("charting_tools.handlers.rule_engine.CurrentNoteStateEvent.objects.filter")
    states.return_value.values_list.return_value = [open_note.dbid]  # the other note is closed
    engine["rule"].rule["conditions"][0]["source"] = "patient"
    effects = RuleEngine(event=_metadata_event(EventType.PATIENT_METADATA_UPDATED, {"patient": {"id": "pt1"}})).compute()
    assert [e.type for e in effects].count(EffectType.BATCH_ORIGINATE_COMMANDS) == 1  # the open note only
    # Notes are read by patient, then their states by note id: no join onto the
    # current-state view.
    assert notes.return_value.defer.return_value.filter.call_args.kwargs == {"patient__id": "pt1"}
    state_kwargs = states.call_args.kwargs
    assert state_kwargs["note_id__in"] == [open_note.dbid, closed.dbid] and "LKD" not in state_kwargs["state__in"]


def test_closed_notes_are_left_alone(open_note: SimpleNamespace, mocker: MagicMock) -> None:
    mocker.patch("charting_tools.handlers.rule_engine.CurrentNoteStateEvent.objects.filter").return_value.exists.return_value = False
    mocker.patch("charting_tools.handlers.rule_engine.Appointment.objects.select_related").return_value.defer.return_value.filter.return_value.first.return_value = (
        SimpleNamespace(note=open_note)
    )
    event = _metadata_event(EventType.APPOINTMENT_METADATA_CREATED, {"appointment": {"id": "appt1"}})
    assert RuleEngine(event=event).compute() == []


# ── Active conditions on the patient ────────────────────────────────

ACTIVE_CKD = {"type": "active_condition", "sources": [{"code": "N18", "include_children": True}]}


def test_active_condition_saves_and_expands_like_a_diagnosis(mocker: MagicMock) -> None:
    mocker.patch("charting_tools.diagnoses.expand_icd10", return_value=["N18", "N186"])
    rule = {"conditions": [dict(ACTIVE_CKD)], "action": {"mode": "suggest"}}
    assert prepare_rule(rule, {"UMLS_API_KEY": "k"}, None, None) is None
    assert rule["conditions"][0]["match_codes"] == ["N18", "N186"]
    cleaned, error = clean_rule({"match": "all", "conditions": [{"type": "active_condition", "sources": []}]})
    assert cleaned is None and error and "choose at least one diagnosis" in error


def test_active_condition_reads_the_patients_problem_list(mocker: MagicMock) -> None:
    active = mocker.patch("charting_tools.rules.Condition.objects.active")
    query = active.return_value.filter
    ckd = SimpleNamespace(codings=MagicMock())
    ckd.codings.all.return_value = [
        SimpleNamespace(system="http://snomed.info/sct", code="433144002"),
        SimpleNamespace(system="ICD-10", code="N18.6"),
    ]
    query.return_value.prefetch_related.return_value = [ckd]
    state = NoteState(SimpleNamespace(id=NOTE_ID, dbid=1, patient_id=7))
    condition = {**ACTIVE_CKD, "match_codes": ["N18", "N186"]}
    assert condition_met(condition, state)
    assert query.call_args.kwargs == {"patient_id": 7, "deleted": False, "surgical": False}
    assert not condition_met({**ACTIVE_CKD, "match_codes": ["E119"]}, state)


def test_active_condition_rules_watch_the_problem_list() -> None:
    assert watched_commands({"conditions": [ACTIVE_CKD]}) == {"created", "patient_conditions"}
    for event in ("CONDITION_CREATED", "CONDITION_UPDATED", "CONDITION_RESOLVED"):
        assert event in RuleEngine.RESPONDS_TO


def test_condition_change_rechecks_the_patients_open_notes(engine: dict, mocker: MagicMock) -> None:
    module = "charting_tools.handlers.rule_engine"
    note = SimpleNamespace(id=NOTE_ID, dbid=1, patient_id=1, datetime_of_service=None, patient=SimpleNamespace(id="pt1"))
    notes = mocker.patch(f"{module}.Note.objects.select_related")
    notes.return_value.defer.return_value.filter.return_value.order_by.return_value.__getitem__.return_value = [note]
    mocker.patch(f"{module}.CurrentNoteStateEvent.objects.filter").return_value.values_list.return_value = [note.dbid]
    engine["rule"] = make_template(template_id="r3", kind="rule", name="CKD", rule={
        "match": "all", "conditions": [{**ACTIVE_CKD, "match_codes": ["N186"]}],
        "action": {"target_id": "t9", "mode": "insert"},
    })
    event = SimpleNamespace(type=EventType.CONDITION_CREATED, name="CONDITION_CREATED",
                            context={"patient": {"id": "pt1"}}, target=SimpleNamespace(id="c1"))
    effects = RuleEngine(event=event).compute()
    assert effects[0].type == EffectType.BATCH_ORIGINATE_COMMANDS
    assert notes.return_value.defer.return_value.filter.call_args.kwargs["patient__id"] == "pt1"


# ── Note type ───────────────────────────────────────────────────────

OFFICE_TYPE = {"type": "note_type", "note_types": [{"unique_identifier": "type-office", "name": "Office visit"}]}


def test_note_type_condition_saves_its_choices() -> None:
    cleaned, error = clean_rule({"match": "all", "conditions": [OFFICE_TYPE], "action": {"mode": "suggest"}})
    assert error is None and cleaned is not None
    assert cleaned["conditions"][0] == OFFICE_TYPE
    cleaned, error = clean_rule({"match": "all", "conditions": [{"type": "note_type", "note_types": []}]})
    assert cleaned is None and error and "choose at least one note type" in error


def _state_with(mocker: MagicMock, appointment_type: str | None, note_type: str | None) -> NoteState:
    appointment = (
        SimpleNamespace(note_type=SimpleNamespace(unique_identifier=appointment_type)) if appointment_type else None
    )
    query = mocker.patch("charting_tools.rules.Appointment.objects.select_related")
    query.return_value.filter.return_value.order_by.return_value.first.return_value = appointment
    note = SimpleNamespace(id=NOTE_ID, dbid=1, patient_id=7,
                           note_type_version=SimpleNamespace(unique_identifier=note_type) if note_type else None)
    return NoteState(note)


def test_booked_note_counts_as_its_appointments_type(mocker: MagicMock) -> None:
    # Booked with Canvas's generic Appointment type; the visit is an office visit.
    assert condition_met(OFFICE_TYPE, _state_with(mocker, "type-office", "type-appointment"))
    assert not condition_met(OFFICE_TYPE, _state_with(mocker, "type-telehealth", "type-appointment"))


def test_note_without_appointment_uses_its_own_type(mocker: MagicMock) -> None:
    assert condition_met(OFFICE_TYPE, _state_with(mocker, None, "type-office"))
    assert not condition_met(OFFICE_TYPE, _state_with(mocker, None, "type-phone"))


def test_note_type_rules_rerun_when_the_visit_type_changes(engine: dict, mocker: MagicMock) -> None:
    module = "charting_tools.handlers.rule_engine"
    assert watched_commands({"conditions": [OFFICE_TYPE]}) == {"created", "visit_type"}
    assert "APPOINTMENT_UPDATED" in RuleEngine.RESPONDS_TO
    note = SimpleNamespace(id=NOTE_ID, dbid=1, patient_id=1, datetime_of_service=None, patient=SimpleNamespace(id="pt1"))
    query = mocker.patch(f"{module}.Appointment.objects.select_related")
    query.return_value.defer.return_value.filter.return_value.exclude.return_value.first.return_value = SimpleNamespace(id="appt2", note=note)
    latest = mocker.patch(f"{module}.Appointment.objects.filter")
    mocker.patch(f"{module}.CurrentNoteStateEvent.objects.filter").return_value.exists.return_value = True
    engine["rule"] = make_template(template_id="r4", kind="rule", name="Office", rule={
        "match": "all", "conditions": [OFFICE_TYPE], "action": {"target_id": "t9", "mode": "insert"}})
    event = SimpleNamespace(type=EventType.APPOINTMENT_UPDATED, name="APPOINTMENT_UPDATED", context={},
                            target=SimpleNamespace(id="appt2"))

    latest.return_value.order_by.return_value.values_list.return_value.first.return_value = "appt2"
    assert RuleEngine(event=event).compute()[0].type == EffectType.BATCH_ORIGINATE_COMMANDS

    # The appointment a reschedule replaced still has the old type: ignored.
    engine["store"].clear()
    latest.return_value.order_by.return_value.values_list.return_value.first.return_value = "appt3"
    assert RuleEngine(event=event).compute() == []


def test_assess_that_diagnoses_a_new_condition_holds_its_code(mocker: MagicMock) -> None:
    # Canvas 1.367: an Assess can diagnose a new condition, and then its
    # condition value is the ICD-10 code rather than a Condition id.
    from charting_tools.note_conditions import note_diagnoses

    query = mocker.patch("charting_tools.note_conditions.Command.objects.filter")
    query.return_value.exclude.return_value.order_by.return_value = [
        SimpleNamespace(schema_key="assess", data={"condition": {"value": "R54", "text": "Age-related physical debility"}}),
    ]
    conditions = mocker.patch("charting_tools.note_conditions.Condition.objects.filter")
    found = note_diagnoses(SimpleNamespace(dbid=1), ("assess", {"condition": {"value": "R54", "text": "Frailty"}}))
    assert [d["code"] for d in found] == ["R54"]
    conditions.assert_not_called()  # no Condition lookup with a code as its id


def test_condition_id_of_tells_ids_from_codes() -> None:
    from charting_tools.icd10 import condition_id_of

    assert condition_id_of(1955) == 1955
    assert condition_id_of("1955") == 1955
    assert condition_id_of("R54") is None
    assert condition_id_of("N18.5") is None
    assert condition_id_of(None) is None
    assert condition_id_of(True) is None
