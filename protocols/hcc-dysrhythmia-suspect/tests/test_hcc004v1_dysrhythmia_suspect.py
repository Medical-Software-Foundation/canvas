"""Tests for the HCC004v1 - Dysrhythmia Suspect protocol plugin."""

from unittest.mock import MagicMock, PropertyMock, patch

from canvas_sdk.effects.protocol_card import ProtocolCard
from canvas_sdk.events import EventType
from protocols.hcc004v1_dysrhythmia_suspect import Hcc004v1


PROTOCOL_MODULE = "protocols.hcc004v1_dysrhythmia_suspect"


def _make_protocol(patient_id: str = "patient-id") -> Hcc004v1:
    """Build an Hcc004v1 with a MEDICATION_LIST_ITEM_UPDATED event for ``patient_id``."""
    event = MagicMock()
    event.type = EventType.MEDICATION_LIST_ITEM_UPDATED
    event.target = MagicMock()
    event.target.id = "medication-id"
    protocol = Hcc004v1(event=event)
    # Pre-populate the cached patient id so patient_id_from_target avoids the DB.
    protocol._patient_id = patient_id
    return protocol


def _stub_queryset_exists(model_cls: MagicMock, *, exists: bool) -> None:
    """Wire a mocked Condition/Medication class so the protocol's chain returns ``exists``."""
    qs = model_cls.objects.for_patient.return_value.active.return_value.find.return_value
    qs.exists.return_value = exists


def test_meta_identifiers() -> None:
    """Identifier and type Meta values are preserved from the source protocol."""
    assert Hcc004v1.Meta.identifiers == ["HCC004v1"]
    assert Hcc004v1.Meta.types == ["HCC"]


def test_meta_description() -> None:
    """Description Meta value is preserved."""
    assert Hcc004v1.Meta.description == (
        "All patients with potential dysrhythmia based on an "
        "active medication without associated active problem."
    )


def test_meta_information() -> None:
    """Information URL Meta value is preserved."""
    assert Hcc004v1.Meta.information == (
        "https://canvas-medical.help.usepylon.com/articles/"
        "7052809697-protocol-dysrhythmia-suspects-hcc004v1"
    )


def test_meta_version() -> None:
    """Version Meta value is preserved."""
    assert Hcc004v1.Meta.version == "2019-02-12v1"


def test_meta_default_permission_flags() -> None:
    """Default permission flag is preserved."""
    assert Hcc004v1.Meta.default_permission_flags == {"protocols:actions:HCC004v1:": True}


def test_responds_to_condition_and_medication_events() -> None:
    """Protocol responds to condition lifecycle and medication list events."""
    assert EventType.Name(EventType.CONDITION_CREATED) in Hcc004v1.RESPONDS_TO
    assert EventType.Name(EventType.CONDITION_UPDATED) in Hcc004v1.RESPONDS_TO
    assert EventType.Name(EventType.CONDITION_ASSESSED) in Hcc004v1.RESPONDS_TO
    assert EventType.Name(EventType.CONDITION_RESOLVED) in Hcc004v1.RESPONDS_TO
    assert EventType.Name(EventType.MEDICATION_LIST_ITEM_CREATED) in Hcc004v1.RESPONDS_TO
    assert EventType.Name(EventType.MEDICATION_LIST_ITEM_UPDATED) in Hcc004v1.RESPONDS_TO


def test_in_initial_population() -> None:
    """All patients are in the initial population."""
    assert _make_protocol().in_initial_population() is True


@patch(f"{PROTOCOL_MODULE}.Medication")
def test_in_denominator_true_with_active_antiarrhythmic(medication_cls: MagicMock) -> None:
    """in_denominator is True when the patient has an active antiarrhythmic medication."""
    _stub_queryset_exists(medication_cls, exists=True)
    assert _make_protocol().in_denominator() is True


@patch(f"{PROTOCOL_MODULE}.Medication")
def test_in_denominator_false_without_active_antiarrhythmic(medication_cls: MagicMock) -> None:
    """in_denominator is False when no active antiarrhythmic medication is present."""
    _stub_queryset_exists(medication_cls, exists=False)
    assert _make_protocol().in_denominator() is False


@patch(f"{PROTOCOL_MODULE}.Condition")
def test_in_numerator_true_without_active_dysrhythmia(condition_cls: MagicMock) -> None:
    """in_numerator is True when the patient has no active dysrhythmia condition."""
    _stub_queryset_exists(condition_cls, exists=False)
    assert _make_protocol().in_numerator() is True


@patch(f"{PROTOCOL_MODULE}.Condition")
def test_in_numerator_false_with_active_dysrhythmia(condition_cls: MagicMock) -> None:
    """in_numerator is False when the patient already has an active dysrhythmia condition."""
    _stub_queryset_exists(condition_cls, exists=True)
    assert _make_protocol().in_numerator() is False


@patch(f"{PROTOCOL_MODULE}.Patient")
@patch(f"{PROTOCOL_MODULE}.Hcc004v1.in_numerator")
@patch(f"{PROTOCOL_MODULE}.Hcc004v1.in_denominator")
def test_compute_not_in_denominator_returns_no_effects(
    in_denominator: MagicMock,
    in_numerator: MagicMock,
    patient_cls: MagicMock,
) -> None:
    """When a patient is not in the denominator, no effects are emitted."""
    in_denominator.return_value = False
    in_numerator.return_value = True

    assert _make_protocol().compute() == []
    patient_cls.objects.get.assert_not_called()


@patch(f"{PROTOCOL_MODULE}.Patient")
@patch(f"{PROTOCOL_MODULE}.Hcc004v1.in_numerator")
@patch(f"{PROTOCOL_MODULE}.Hcc004v1.in_denominator")
def test_compute_in_denominator_not_in_numerator_is_satisfied(
    in_denominator: MagicMock,
    in_numerator: MagicMock,
    patient_cls: MagicMock,
) -> None:
    """A patient with both an active antiarrhythmic and active dysrhythmia is satisfied."""
    in_denominator.return_value = True
    in_numerator.return_value = False

    effects = _make_protocol().compute()

    assert len(effects) == 1
    payload = effects[0].payload
    assert ProtocolCard.Status.SATISFIED.value in payload
    patient_cls.objects.get.assert_not_called()


@patch(f"{PROTOCOL_MODULE}.Patient")
@patch(f"{PROTOCOL_MODULE}.Hcc004v1.in_numerator")
@patch(f"{PROTOCOL_MODULE}.Hcc004v1.in_denominator")
def test_compute_in_denominator_in_numerator_is_due_with_recommendation(
    in_denominator: MagicMock,
    in_numerator: MagicMock,
    patient_cls: MagicMock,
) -> None:
    """A dysrhythmia-suspect patient gets a due protocol card with a Diagnose recommendation."""
    in_denominator.return_value = True
    in_numerator.return_value = True
    patient_cls.objects.get.return_value = MagicMock(first_name="Jim")

    effects = _make_protocol().compute()

    assert len(effects) == 1
    payload = effects[0].payload
    assert ProtocolCard.Status.DUE.value in payload
    assert (
        "Jim has an active medication on the Medication List "
        "commonly used for Dysrhythmia. There is no associated condition on "
        "the Conditions List."
    ) in payload
    assert (
        "Consider updating the Conditions List to include Dysrhythmia "
        "related problem as clinically appropriate."
    ) in payload
    assert "Diagnose" in payload
    assert "diagnose" in payload
