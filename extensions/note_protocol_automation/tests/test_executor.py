"""Executor: NOTE_STATE_CHANGE_EVENT_CREATED -> (gate on NEW) -> resolve note type
-> match rules -> one batch effect.

Factory imports are inside each test (matching the sibling test_signals): a
top-level import of canvas_sdk factories breaks Django app-loading at collection
time. gather_signals is monkeypatched to a known PatientSignals so these tests
exercise the executor's gate/resolve/match/emit path, not the DB-read layer (which
is covered exhaustively in test_signals)."""

from typing import Any

import pytest

from note_protocol_automation.handlers.executor import ProtocolExecutor
from note_protocol_automation.lib.types import PatientSignals
from note_protocol_automation.models.rule import Rule

_SIGNALS = PatientSignals(frozenset(), 66, "F", {}, frozenset())


def _make_handler(note_id: str, patient_key: str, state: str = "NEW") -> ProtocolExecutor:
    """Construct the handler with a test seam carrying the state-change context."""
    h = ProtocolExecutor.__new__(ProtocolExecutor)
    h._event_context = {"note_id": note_id, "patient_id": patient_key, "state": state}
    return h


@pytest.mark.integtest
@pytest.mark.django_db
def test_matching_rule_emits_batch_originate(monkeypatch: pytest.MonkeyPatch) -> None:
    """A NEW-state note whose type has a matching rule yields one BatchOriginate effect."""
    from canvas_sdk.test_utils.factories import NoteFactory, NoteTypeFactory, PatientFactory

    nt = NoteTypeFactory.create(name="Annual Physical Visit")
    patient = PatientFactory.create()
    note = NoteFactory.create(patient=patient, note_type_version=nt)

    rule = Rule(
        name="annual physical",
        note_type_id=str(nt.unique_identifier),
        enabled=True,
        match="all",
        priority=0,
    )
    rule.set_predicates([{"signal": "age", "operator": ">=", "value": 18}])
    rule.set_commands(["diagnose", "plan"])
    rule.save()

    handler = _make_handler(str(note.id), str(patient.id), state="NEW")
    monkeypatch.setattr(
        "note_protocol_automation.handlers.executor.gather_signals",
        lambda *a, **k: _SIGNALS,
    )
    effects = handler.compute()
    assert len(effects) == 1  # one BatchOriginateCommandEffect


@pytest.mark.integtest
@pytest.mark.django_db
def test_no_matching_rule_emits_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """A NEW-state note type with no enabled rule yields no effects."""
    from canvas_sdk.test_utils.factories import NoteFactory, NoteTypeFactory, PatientFactory

    nt = NoteTypeFactory.create(name="Unconfigured")
    patient = PatientFactory.create()
    note = NoteFactory.create(patient=patient, note_type_version=nt)

    handler = _make_handler(str(note.id), str(patient.id), state="NEW")
    monkeypatch.setattr(
        "note_protocol_automation.handlers.executor.gather_signals",
        lambda *a, **k: _SIGNALS,
    )
    effects: Any = handler.compute()
    assert effects == []


@pytest.mark.integtest
@pytest.mark.django_db
def test_non_new_state_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """A later state change (e.g. SIGNED) on a note WITH a matching rule inserts
    nothing — the NEW gate prevents re-inserting commands on sign/lock/etc."""
    from canvas_sdk.test_utils.factories import NoteFactory, NoteTypeFactory, PatientFactory

    nt = NoteTypeFactory.create(name="Annual Physical Visit")
    patient = PatientFactory.create()
    note = NoteFactory.create(patient=patient, note_type_version=nt)

    rule = Rule(
        name="annual physical",
        note_type_id=str(nt.unique_identifier),
        enabled=True,
        match="all",
        priority=0,
    )
    rule.set_predicates([{"signal": "age", "operator": ">=", "value": 18}])
    rule.set_commands(["diagnose", "plan"])
    rule.save()

    # Same matching rule, but the event is a SIGNED state change, not NEW.
    handler = _make_handler(str(note.id), str(patient.id), state="SGN")
    monkeypatch.setattr(
        "note_protocol_automation.handlers.executor.gather_signals",
        lambda *a, **k: _SIGNALS,
    )
    assert handler.compute() == []


def _seed_matching_rule(
    monkeypatch: pytest.MonkeyPatch, raise_exc: Exception
) -> ProtocolExecutor:
    """Seed a note + matching rule, then make gather_signals raise `raise_exc`.

    Returns a handler whose compute() reaches the gather_signals call (past every
    early return) so the exception path is exercised."""
    from canvas_sdk.test_utils.factories import NoteFactory, NoteTypeFactory, PatientFactory

    nt = NoteTypeFactory.create(name="Annual Physical Visit")
    patient = PatientFactory.create()
    note = NoteFactory.create(patient=patient, note_type_version=nt)
    rule = Rule(name="annual physical", note_type_id=str(nt.unique_identifier), enabled=True)
    rule.set_predicates([{"signal": "age", "operator": ">=", "value": 18}])
    rule.set_commands(["diagnose"])
    rule.save()

    def _raise(*a: Any, **k: Any) -> Any:
        raise raise_exc

    monkeypatch.setattr(
        "note_protocol_automation.handlers.executor.gather_signals", _raise
    )
    return _make_handler(str(note.id), str(patient.id), state="NEW")


@pytest.mark.integtest
@pytest.mark.django_db
def test_match_any_rule_wired_through_executor(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end wiring of the `match` field: a DB-persisted rule with match="any"
    and one passing + one failing predicate fires (emits a batch effect), whereas
    the same rule under match="all" emits nothing. This guards against the executor
    dropping `match` from its .values()/parsed dict (which would silently default
    every rule back to "all" while the matching.py unit test stayed green)."""
    from canvas_sdk.test_utils.factories import NoteFactory, NoteTypeFactory, PatientFactory

    nt = NoteTypeFactory.create(name="Annual Physical Visit")
    patient = PatientFactory.create()
    note = NoteFactory.create(patient=patient, note_type_version=nt)
    monkeypatch.setattr(
        "note_protocol_automation.handlers.executor.gather_signals",
        lambda *a, **k: _SIGNALS,  # age 66, sex F
    )

    def _save_rule(match: str) -> Rule:
        Rule.objects.all().delete()
        rule = Rule(
            name="any-rule", note_type_id=str(nt.unique_identifier), enabled=True, match=match
        )
        rule.set_predicates(
            [
                {"signal": "age", "operator": ">=", "value": 18},  # passes (66)
                {"signal": "sex", "operator": "==", "value": "M"},  # fails (F)
            ]
        )
        rule.set_commands(["diagnose"])
        rule.save()
        return rule

    _save_rule("any")
    handler = _make_handler(str(note.id), str(patient.id), state="NEW")
    assert len(handler.compute()) == 1  # one predicate passed -> rule fires

    _save_rule("all")
    handler = _make_handler(str(note.id), str(patient.id), state="NEW")
    assert handler.compute() == []  # one predicate failed -> rule does NOT fire


@pytest.mark.integtest
@pytest.mark.django_db
def test_expected_error_is_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """An expected parse-shape error (ValueError) never blocks the note -> []."""
    handler = _seed_matching_rule(monkeypatch, ValueError("bad rule config"))
    assert handler.compute() == []


@pytest.mark.integtest
@pytest.mark.django_db
def test_unexpected_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    """An UNEXPECTED error (RuntimeError) is NOT swallowed — it propagates so the
    platform surfaces it (Sentry) rather than silently masking a real bug."""
    handler = _seed_matching_rule(monkeypatch, RuntimeError("boom"))
    with pytest.raises(RuntimeError, match="boom"):
        handler.compute()
