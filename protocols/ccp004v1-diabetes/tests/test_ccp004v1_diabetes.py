"""Tests for the CCP004v1 — Diagnosis Of Diabetes protocol plugin."""

from datetime import date
from unittest.mock import MagicMock, PropertyMock, patch

from canvas_sdk.effects.protocol_card import ProtocolCard
from canvas_sdk.events import EventType
from protocols.ccp004v1_diabetes import Ccp004v1


PROTOCOL_MODULE = "protocols.ccp004v1_diabetes"


def _make_protocol(patient_id: str = "patient-id") -> Ccp004v1:
    """Build a Ccp004v1 with a CONDITION_UPDATED event for ``patient_id``."""
    event = MagicMock()
    event.type = EventType.CONDITION_UPDATED
    event.target = MagicMock()
    event.target.id = "condition-id"
    protocol = Ccp004v1(event=event)
    # Pre-populate the cached patient id so patient_id_from_target avoids the DB.
    protocol._patient_id = patient_id
    return protocol


def _condition(onset: date | None) -> MagicMock:
    """Build a fake Condition stand-in with an ``onset_date`` attribute."""
    condition = MagicMock()
    condition.onset_date = onset
    return condition


def _stub_active_diabetes(condition_cls: MagicMock, conditions: list[MagicMock]) -> None:
    """Wire the mocked Condition class so the protocol's queryset chain returns ``conditions``."""
    qs = condition_cls.objects.for_patient.return_value.find.return_value.active.return_value
    qs.order_by.return_value = conditions


def test_meta_identifiers() -> None:
    """Identifier and type Meta values are preserved from the source protocol."""
    assert Ccp004v1.Meta.identifiers == ["CCP004v1"]
    assert Ccp004v1.Meta.types == ["CCP"]


def test_meta_description() -> None:
    """Description Meta value is preserved."""
    assert Ccp004v1.Meta.description == "All patients with Diagnosis Of Diabetes."


def test_meta_information() -> None:
    """Information URL Meta value is preserved."""
    assert Ccp004v1.Meta.information == "https://canvas-medical.help.usepylon.com/"


def test_meta_version() -> None:
    """Version Meta value is preserved."""
    assert Ccp004v1.Meta.version == "2020-04-02v1"


def test_responds_to_condition_events() -> None:
    """Protocol responds to the condition lifecycle event types."""
    assert EventType.Name(EventType.CONDITION_CREATED) in Ccp004v1.RESPONDS_TO
    assert EventType.Name(EventType.CONDITION_UPDATED) in Ccp004v1.RESPONDS_TO
    assert EventType.Name(EventType.CONDITION_ASSESSED) in Ccp004v1.RESPONDS_TO
    assert EventType.Name(EventType.CONDITION_RESOLVED) in Ccp004v1.RESPONDS_TO


def test_in_initial_population() -> None:
    """All patients are in the initial population."""
    assert _make_protocol().in_initial_population() is True


def test_in_denominator() -> None:
    """All patients are in the denominator."""
    assert _make_protocol().in_denominator() is True


@patch(f"{PROTOCOL_MODULE}.Condition")
def test_date_of_diagnosis_no_conditions(condition_cls: MagicMock) -> None:
    """When the patient has no active diabetes conditions, date_of_diagnosis is ''."""
    _stub_active_diabetes(condition_cls, [])
    assert _make_protocol().date_of_diagnosis == ""


@patch(f"{PROTOCOL_MODULE}.Condition")
def test_date_of_diagnosis_single_condition(condition_cls: MagicMock) -> None:
    """A single active diabetes condition yields its onset date."""
    _stub_active_diabetes(condition_cls, [_condition(date(2018, 8, 20))])
    assert _make_protocol().date_of_diagnosis == "2018-08-20"


@patch(f"{PROTOCOL_MODULE}.Condition")
def test_date_of_diagnosis_multiple_returns_oldest(condition_cls: MagicMock) -> None:
    """Multiple active conditions return the earliest onset (order_by handles sorting)."""
    _stub_active_diabetes(
        condition_cls,
        [
            _condition(date(2018, 8, 17)),
            _condition(date(2018, 8, 18)),
            _condition(date(2018, 8, 19)),
        ],
    )
    assert _make_protocol().date_of_diagnosis == "2018-08-17"


@patch(f"{PROTOCOL_MODULE}.Condition")
def test_in_numerator_false_when_no_conditions(condition_cls: MagicMock) -> None:
    """in_numerator is False when there are no active diabetes conditions."""
    _stub_active_diabetes(condition_cls, [])
    assert _make_protocol().in_numerator() is False


@patch(f"{PROTOCOL_MODULE}.Condition")
def test_in_numerator_true_with_active_condition(condition_cls: MagicMock) -> None:
    """in_numerator is True when there is an active diabetes condition with an onset."""
    _stub_active_diabetes(condition_cls, [_condition(date(2018, 8, 20))])
    assert _make_protocol().in_numerator() is True


@patch(f"{PROTOCOL_MODULE}.Patient")
@patch(f"{PROTOCOL_MODULE}.Ccp004v1.date_of_diagnosis", new_callable=PropertyMock)
@patch(f"{PROTOCOL_MODULE}.Ccp004v1.in_numerator")
@patch(f"{PROTOCOL_MODULE}.Ccp004v1.in_denominator")
def test_compute_not_in_denominator_returns_no_effects(
    in_denominator: MagicMock,
    in_numerator: MagicMock,
    date_of_diagnosis: PropertyMock,
    patient_cls: MagicMock,
) -> None:
    """When a patient is not in the denominator, no effects are emitted."""
    in_denominator.return_value = False
    in_numerator.return_value = True
    date_of_diagnosis.return_value = "2017-03-14"

    assert _make_protocol().compute() == []
    patient_cls.objects.get.assert_not_called()


@patch(f"{PROTOCOL_MODULE}.Patient")
@patch(f"{PROTOCOL_MODULE}.Ccp004v1.date_of_diagnosis", new_callable=PropertyMock)
@patch(f"{PROTOCOL_MODULE}.Ccp004v1.in_numerator")
@patch(f"{PROTOCOL_MODULE}.Ccp004v1.in_denominator")
def test_compute_in_denominator_not_in_numerator_is_satisfied(
    in_denominator: MagicMock,
    in_numerator: MagicMock,
    date_of_diagnosis: PropertyMock,
    patient_cls: MagicMock,
) -> None:
    """A non-diabetic patient gets a satisfied protocol card with the expected narrative."""
    in_denominator.return_value = True
    in_numerator.return_value = False
    date_of_diagnosis.return_value = ""
    patient_cls.objects.get.return_value = MagicMock(first_name="Nicolas")

    effects = _make_protocol().compute()

    assert len(effects) == 1
    # Round-trip the rendered effect payload to confirm the card's user-visible state.
    payload = effects[0].payload
    assert "Nicolas has not been diagnosed of diabetes." in payload
    assert ProtocolCard.Status.SATISFIED.value in payload


@patch(f"{PROTOCOL_MODULE}.Patient")
@patch(f"{PROTOCOL_MODULE}.Ccp004v1.date_of_diagnosis", new_callable=PropertyMock)
@patch(f"{PROTOCOL_MODULE}.Ccp004v1.in_numerator")
@patch(f"{PROTOCOL_MODULE}.Ccp004v1.in_denominator")
def test_compute_in_denominator_in_numerator_is_due_with_recommendation(
    in_denominator: MagicMock,
    in_numerator: MagicMock,
    date_of_diagnosis: PropertyMock,
    patient_cls: MagicMock,
) -> None:
    """A diabetic patient gets a due protocol card with a "Contact the patient" recommendation."""
    in_denominator.return_value = True
    in_numerator.return_value = True
    date_of_diagnosis.return_value = "2017-03-14"
    patient_cls.objects.get.return_value = MagicMock(first_name="Nicolas")

    effects = _make_protocol().compute()

    assert len(effects) == 1
    payload = effects[0].payload
    assert "Nicolas has been diagnosed of diabetes on Tue, Mar 14th 2017." in payload
    assert ProtocolCard.Status.DUE.value in payload
    assert "Contact the patient" in payload
    assert "Schedule" in payload
    assert "schedule" in payload
