import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from auto_fax.handlers.note_locked import CANVAS_BOT_STAFF_ID, AutoFaxOnNoteLock
from auto_fax.services.config import CoverSheet, RecipientSpec, Rule
from auto_fax.services.recipients import Recipient

MODULE = "auto_fax.handlers.note_locked"


def _rule(name="pcp", states=("LKD",), cover=None, codes=("office_visit",)):
    return Rule(
        name=name,
        note_type_codes=frozenset(codes),
        trigger_states=frozenset(states),
        recipients=(RecipientSpec(type="facility"),),
        cover_sheet=cover,
    )


def _rule_json(**overrides):
    rule = {
        "name": "pcp",
        "note_type_codes": ["office_visit"],
        "trigger_states": ["LKD", "SGN"],
        "recipients": [{"type": "facility"}],
    }
    rule.update(overrides)
    return rule


def _handler(state="LKD", note_id="note-1", mode="live", rules=None, test_number=""):
    event = SimpleNamespace(
        context={"note_id": note_id, "state": state} if note_id else {"state": state}
    )
    secrets = {
        "AUTO_FAX_MODE": mode,
        "AUTO_FAX_RULES": json.dumps(rules if rules is not None else [_rule_json()]),
        "AUTO_FAX_TEST_FAX_NUMBER": test_number,
    }
    handler = AutoFaxOnNoteLock.__new__(AutoFaxOnNoteLock)
    handler.event = event
    handler.secrets = secrets
    return handler


def _note(code="office_visit", location_id="loc-1", patient=True):
    return SimpleNamespace(
        id="note-1",
        note_type_version=SimpleNamespace(code=code) if code else None,
        patient=SimpleNamespace(id="patient-1") if patient else None,
        location=SimpleNamespace(id=location_id) if location_id else None,
    )


@pytest.fixture
def env():
    with (
        patch(f"{MODULE}.Note") as note_model,
        patch(f"{MODULE}.NoteActionEvent") as action_event,
        patch(f"{MODULE}.FaxNoteEffect") as fax_effect,
        patch(f"{MODULE}.resolve_recipients") as resolve,
        patch(f"{MODULE}.date") as fake_date,
        patch(f"{MODULE}.log") as log,
    ):
        fake_date.today.return_value = date(2026, 11, 2)
        note_first = (
            note_model.objects.select_related.return_value.filter.return_value.first
        )
        note_first.return_value = _note()
        faxed = (
            action_event.objects.filter.return_value.exclude.return_value.values_list
        )
        faxed.return_value = []
        yield SimpleNamespace(
            note_model=note_model,
            note_first=note_first,
            action_event=action_event,
            faxed=faxed,
            fax_effect=fax_effect,
            resolve=resolve,
            log=log,
        )


def _recipient(
    rule, digits="5552340111", name="Oak House", kind="facility", problem=None
):
    return Recipient(rule, kind, name, digits, problem=problem)


def test_responds_to_note_state_change():
    assert AutoFaxOnNoteLock.RESPONDS_TO == "NOTE_STATE_CHANGE_EVENT_CREATED"


@pytest.mark.parametrize(
    "handler",
    [
        _handler(note_id=None),
        _handler(state="NEW"),
        _handler(state="ULK"),
        _handler(mode="off"),
        _handler(mode=""),
        _handler(rules=[]),
        _handler(state="RLK"),  # the rule only fires on LKD and SGN
    ],
)
def test_bails_out_before_any_query(env, handler):
    assert handler.compute() == []
    env.note_model.objects.select_related.assert_not_called()
    env.resolve.assert_not_called()


def test_missing_context_is_handled():
    handler = _handler()
    handler.event = SimpleNamespace(context=None)
    assert handler.compute() == []


@pytest.mark.parametrize("note", [None, _note(patient=False)])
def test_missing_note_or_patient(env, note):
    env.note_first.return_value = note
    assert _handler().compute() == []
    env.resolve.assert_not_called()
    env.log.info.assert_called_once_with(
        "[auto_fax] note note-1: no note or no patient, skipping"
    )


def test_note_loaded_in_one_query(env):
    env.resolve.return_value = []
    _handler().compute()
    env.note_model.objects.select_related.assert_called_once_with(
        "note_type_version", "patient", "location"
    )
    env.note_model.objects.select_related.return_value.filter.assert_called_once_with(
        id="note-1"
    )


@pytest.mark.parametrize("note", [_note(code="telehealth"), _note(code=None)])
def test_note_type_not_in_any_rule(env, note):
    env.note_first.return_value = note
    assert _handler().compute() == []
    env.resolve.assert_not_called()


def test_no_sendable_recipients(env):
    env.resolve.side_effect = lambda patient_id, rules, today: [
        _recipient(rules[0], digits=None, problem="facility has no valid fax number")
    ]
    assert _handler().compute() == []
    env.log.warning.assert_called_once_with(
        "[auto_fax] note note-1 rule 'pcp': skipped facility 'Oak House': facility has no valid fax number"
    )
    env.action_event.objects.filter.assert_not_called()


def test_live_sends_one_fax_per_recipient(env):
    env.resolve.side_effect = lambda patient_id, rules, today: [_recipient(rules[0])]
    effects = _handler().compute()

    assert effects == [env.fax_effect.return_value.apply.return_value]
    env.resolve.assert_called_once()
    assert env.resolve.call_args.args[0] == "patient-1"
    assert env.resolve.call_args.args[2] == date(2026, 11, 2)
    env.fax_effect.assert_called_once_with(
        note_id="note-1", recipient_name="Oak House", recipient_fax_number="15552340111"
    )
    env.log.info.assert_called_once_with(
        "[auto_fax] faxing note note-1 rule 'pcp' -> facility 'Oak House' at ***-***-0111"
    )
    env.action_event.objects.filter.assert_called_once_with(
        note__id="note-1", event_type="FAXED", originator__staff__id=CANVAS_BOT_STAFF_ID
    )
    env.action_event.objects.filter.return_value.exclude.assert_called_once_with(
        delivered_by_fax=False
    )
    env.faxed.assert_called_once_with("fax__to_fax_number", flat=True)


def test_signed_state_fires_rules_listing_it(env):
    env.resolve.side_effect = lambda patient_id, rules, today: [_recipient(rules[0])]
    assert len(_handler(state="SGN").compute()) == 1


def test_dry_run_logs_and_sends_nothing(env):
    env.resolve.side_effect = lambda patient_id, rules, today: [_recipient(rules[0])]
    assert _handler(mode="dry_run").compute() == []
    env.fax_effect.assert_not_called()
    env.log.info.assert_called_once_with(
        "[auto_fax] dry run, would fax note note-1 rule 'pcp' -> facility 'Oak House' at ***-***-0111"
    )


def test_test_number_replaces_every_destination(env):
    env.resolve.side_effect = lambda patient_id, rules, today: [
        _recipient(rules[0]),
        _recipient(rules[0], digits="5552340122", name="Other"),
    ]
    effects = _handler(test_number="555-234-0199").compute()

    # Both recipients now share one destination, but each is a separate
    # recipient so a practice can see every fax the rules would send.
    assert len(effects) == 2
    numbers = {
        call.kwargs["recipient_fax_number"] for call in env.fax_effect.call_args_list
    }
    assert numbers == {"15552340199"}
    env.log.info.assert_any_call(
        "[auto_fax] faxing note note-1 rule 'pcp' -> facility 'Oak House' at ***-***-0199 (test number)"
    )


def test_duplicate_numbers_are_faxed_once(env):
    env.resolve.side_effect = lambda patient_id, rules, today: [
        _recipient(rules[0]),
        _recipient(rules[0]),
    ]
    assert len(_handler().compute()) == 1


def test_already_faxed_numbers_are_skipped(env):
    env.faxed.return_value = ["+15552340111", None]
    env.resolve.side_effect = lambda patient_id, rules, today: [
        _recipient(rules[0]),
        _recipient(rules[0], digits="5552340122", name="Other"),
    ]
    _handler().compute()
    env.fax_effect.assert_called_once_with(
        note_id="note-1", recipient_name="Other", recipient_fax_number="15552340122"
    )


def test_relock_always_sends_again(env):
    env.faxed.return_value = ["+15552340111"]
    env.resolve.side_effect = lambda patient_id, rules, today: [_recipient(rules[0])]
    effects = _handler(
        state="RLK", rules=[_rule_json(trigger_states=["RLK"])]
    ).compute()
    assert len(effects) == 1
    env.action_event.objects.filter.assert_not_called()


def test_cover_sheet_is_added(env):
    cover = {"subject": "Visit note", "comment": "Please file."}
    env.resolve.side_effect = lambda patient_id, rules, today: [_recipient(rules[0])]
    _handler(rules=[_rule_json(cover_sheet=cover)]).compute()
    env.fax_effect.assert_called_once_with(
        note_id="note-1",
        recipient_name="Oak House",
        recipient_fax_number="15552340111",
        include_coversheet=True,
        subject="Visit note",
        comment="Please file.",
        location_id="loc-1",
    )


def test_cover_sheet_dropped_without_a_location(env):
    env.note_first.return_value = _note(location_id=None)
    cover = {"subject": "Visit note", "comment": "Please file."}
    env.resolve.side_effect = lambda patient_id, rules, today: [_recipient(rules[0])]
    _handler(rules=[_rule_json(cover_sheet=cover)]).compute()
    env.fax_effect.assert_called_once_with(
        note_id="note-1", recipient_name="Oak House", recipient_fax_number="15552340111"
    )
    env.log.warning.assert_called_once_with(
        "[auto_fax] note note-1 has no practice location; sending rule 'pcp' without its coversheet"
    )


def test_only_matching_rules_are_resolved(env):
    env.resolve.return_value = []
    rules = [
        _rule_json(name="visits"),
        _rule_json(name="telehealth", note_type_codes=["telehealth"]),
        _rule_json(name="relock only", trigger_states=["RLK"]),
    ]
    _handler(rules=rules).compute()
    (resolved_rules,) = [call.args[1] for call in env.resolve.call_args_list]
    assert [rule.name for rule in resolved_rules] == ["visits"]


def test_fax_effect_helper_without_cover():
    rule = _rule(cover=None)
    with patch(f"{MODULE}.FaxNoteEffect") as fax_effect:
        AutoFaxOnNoteLock._fax_effect("note-1", _recipient(rule), "5552340111", None)
    fax_effect.assert_called_once_with(
        note_id="note-1", recipient_name="Oak House", recipient_fax_number="15552340111"
    )


def test_fax_effect_helper_with_cover():
    rule = _rule(cover=CoverSheet(subject="S", comment="C"))
    with patch(f"{MODULE}.FaxNoteEffect") as fax_effect:
        AutoFaxOnNoteLock._fax_effect("note-1", _recipient(rule), "5552340111", "loc-9")
    assert fax_effect.call_args.kwargs["location_id"] == "loc-9"
    fax_effect.return_value.apply.assert_called_once_with()
