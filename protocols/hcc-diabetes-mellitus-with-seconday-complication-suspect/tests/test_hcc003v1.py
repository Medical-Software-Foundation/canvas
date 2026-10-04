"""Tests for the HCC003v1 - Diabetes Mellitus With Secondary Complication Suspect plugin."""

import json
from unittest.mock import MagicMock, PropertyMock, patch

from canvas_sdk.effects.protocol_card import ProtocolCard
from canvas_sdk.events import EventType

from protocols.hcc003v1_diabetes_secondary_complication import Hcc003v1

PROTOCOL_MODULE = "protocols.hcc003v1_diabetes_secondary_complication"


def _make_protocol(patient_id: str = "patient-id") -> Hcc003v1:
    """Build an ``Hcc003v1`` with a CONDITION_UPDATED event for ``patient_id``."""
    event = MagicMock()
    event.type = EventType.CONDITION_UPDATED
    event.target = MagicMock()
    event.target.id = "condition-id"
    protocol = Hcc003v1(event=event)
    protocol._patient_id = patient_id  # short-circuit DB lookup in patient_id_from_target
    return protocol


def test_meta_identifiers() -> None:
    """Identifier and type Meta values are preserved from the source protocol."""
    assert Hcc003v1.Meta.identifiers == ["HCC003v1"]
    assert Hcc003v1.Meta.types == ["HCC"]


def test_meta_description() -> None:
    """Description Meta value is preserved."""
    expected = (
        "All patients with diabetes, uncomplicated AND a "
        "2ndary condition often associated with diabetes."
    )
    assert Hcc003v1.Meta.description == expected


def test_meta_information() -> None:
    """Information URL Meta value is preserved."""
    expected = "https://canvas-medical.help.usepylon.com/articles/2137336140-protocol-diabetes-mellitus-secondary-complication"
    assert Hcc003v1.Meta.information == expected


def test_meta_version() -> None:
    """Version Meta value is preserved."""
    assert Hcc003v1.Meta.version == "2019-02-12v1"


def test_responds_to_condition_events() -> None:
    """Protocol responds to the four condition lifecycle event types."""
    assert EventType.Name(EventType.CONDITION_CREATED) in Hcc003v1.RESPONDS_TO
    assert EventType.Name(EventType.CONDITION_UPDATED) in Hcc003v1.RESPONDS_TO
    assert EventType.Name(EventType.CONDITION_ASSESSED) in Hcc003v1.RESPONDS_TO
    assert EventType.Name(EventType.CONDITION_RESOLVED) in Hcc003v1.RESPONDS_TO


def test_in_initial_population() -> None:
    """All patients are in the initial population."""
    assert _make_protocol().in_initial_population() is True


def _wire_has_active(condition_cls: MagicMock, mapping: dict[str, bool]) -> None:
    """Make ``condition_cls.objects.for_patient(...).find(VS).active().exists()`` reflect ``mapping``.

    ``mapping`` keys are value set class names (e.g. "DiabetesWithoutComplication"); missing
    keys default to ``False``.
    """

    def find(value_set: type) -> MagicMock:
        match = MagicMock()
        match.active.return_value.exists.return_value = mapping.get(value_set.__name__, False)
        return match

    condition_cls.objects.for_patient.return_value.find.side_effect = find


@patch(f"{PROTOCOL_MODULE}.Condition")
def test_in_denominator_false_without_e119(condition_cls: MagicMock) -> None:
    """Without an active E11.9 diagnosis the patient is not in the denominator."""
    condition_cls.objects.for_patient.return_value.find.return_value.active.return_value.exists.return_value = (
        False
    )
    assert _make_protocol().in_denominator() is False


@patch(f"{PROTOCOL_MODULE}.Condition")
def test_in_denominator_true_with_e119(condition_cls: MagicMock) -> None:
    """An active E11.9 diagnosis puts the patient in the denominator."""
    condition_cls.objects.for_patient.return_value.find.return_value.active.return_value.exists.return_value = (
        True
    )
    assert _make_protocol().in_denominator() is True


@patch(f"{PROTOCOL_MODULE}.Condition")
def test_has_suspect_eye_condition_matches_either_value_set(condition_cls: MagicMock) -> None:
    """Eye-suspect is True if either the code or the class value set matches."""
    _wire_has_active(condition_cls, {"DiabetesEyeConditionSuspect": True})
    assert _make_protocol().has_suspect_eye_condition is True

    condition_cls.reset_mock()
    _wire_has_active(condition_cls, {"DiabetesEyeClassConditionSuspect": True})
    assert _make_protocol().has_suspect_eye_condition is True

    condition_cls.reset_mock()
    _wire_has_active(condition_cls, {})
    assert _make_protocol().has_suspect_eye_condition is False


@patch(f"{PROTOCOL_MODULE}.Condition")
def test_in_numerator_true_for_any_suspect(condition_cls: MagicMock) -> None:
    """A single suspect category is enough to be in the numerator."""
    for vs_name in [
        "DiabetesEyeConditionSuspect",
        "DiabetesNeurologicConditionSuspect",
        "DiabetesRenalConditionSuspect",
        "DiabetesCirculatoryClassConditionSuspect",
        "DiabetesOtherClassConditionSuspect",
    ]:
        condition_cls.reset_mock()
        _wire_has_active(condition_cls, {vs_name: True})
        assert _make_protocol().in_numerator() is True, vs_name


@patch(f"{PROTOCOL_MODULE}.Condition")
def test_in_numerator_false_without_any_suspect(condition_cls: MagicMock) -> None:
    """No suspect categories means in_numerator is False."""
    _wire_has_active(condition_cls, {})
    assert _make_protocol().in_numerator() is False


@patch(f"{PROTOCOL_MODULE}.Patient")
@patch(f"{PROTOCOL_MODULE}.Hcc003v1.in_numerator")
@patch(f"{PROTOCOL_MODULE}.Hcc003v1.in_denominator")
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
@patch(f"{PROTOCOL_MODULE}.Hcc003v1.in_numerator")
@patch(f"{PROTOCOL_MODULE}.Hcc003v1.in_denominator")
def test_compute_in_denominator_not_in_numerator_is_satisfied(
    in_denominator: MagicMock,
    in_numerator: MagicMock,
    patient_cls: MagicMock,
) -> None:
    """A patient with E11.9 but no secondary complication gets a satisfied card."""
    in_denominator.return_value = True
    in_numerator.return_value = False
    effects = _make_protocol().compute()

    assert len(effects) == 1
    patient_cls.objects.get.assert_not_called()


@patch(f"{PROTOCOL_MODULE}.Patient")
@patch(f"{PROTOCOL_MODULE}.Hcc003v1.has_suspect_other_condition", new_callable=PropertyMock)
@patch(f"{PROTOCOL_MODULE}.Hcc003v1.has_suspect_circulatory_condition", new_callable=PropertyMock)
@patch(f"{PROTOCOL_MODULE}.Hcc003v1.has_suspect_renal_condition", new_callable=PropertyMock)
@patch(f"{PROTOCOL_MODULE}.Hcc003v1.has_suspect_neurologic_condition", new_callable=PropertyMock)
@patch(f"{PROTOCOL_MODULE}.Hcc003v1.has_suspect_eye_condition", new_callable=PropertyMock)
@patch(f"{PROTOCOL_MODULE}.Hcc003v1.in_numerator")
@patch(f"{PROTOCOL_MODULE}.Hcc003v1.in_denominator")
def test_compute_due_for_eye_suspect_only(
    in_denominator: MagicMock,
    in_numerator: MagicMock,
    eye: PropertyMock,
    neuro: PropertyMock,
    renal: PropertyMock,
    circ: PropertyMock,
    other: PropertyMock,
    patient_cls: MagicMock,
) -> None:
    """Eye-only suspect builds the expected narrative and a single Diagnose recommendation."""
    in_denominator.return_value = True
    in_numerator.return_value = True
    eye.return_value = True
    neuro.return_value = False
    renal.return_value = False
    circ.return_value = False
    other.return_value = False
    patient_cls.objects.get.return_value = MagicMock(first_name="Jim")

    effects = _make_protocol().compute()

    assert len(effects) == 1
    data = json.loads(effects[0].payload)["data"]
    assert data["status"] == ProtocolCard.Status.DUE.value
    assert data["due_in"] == -1
    assert data["narrative"] == (
        "Jim has Diabetes without complications AND "
        "an eye condition commonly caused by diabetes on the Conditions list."
    )
    recommendations = data["recommendations"]
    assert len(recommendations) == 1
    assert recommendations[0]["title"] == (
        "Consider updating the Diabetes without complications (E11.9) "
        "to Diabetes with secondary eye disease as clinically appropriate."
    )
    assert recommendations[0]["button"] == "Diagnose"


@patch(f"{PROTOCOL_MODULE}.Patient")
@patch(f"{PROTOCOL_MODULE}.Hcc003v1.has_suspect_other_condition", new_callable=PropertyMock)
@patch(f"{PROTOCOL_MODULE}.Hcc003v1.has_suspect_circulatory_condition", new_callable=PropertyMock)
@patch(f"{PROTOCOL_MODULE}.Hcc003v1.has_suspect_renal_condition", new_callable=PropertyMock)
@patch(f"{PROTOCOL_MODULE}.Hcc003v1.has_suspect_neurologic_condition", new_callable=PropertyMock)
@patch(f"{PROTOCOL_MODULE}.Hcc003v1.has_suspect_eye_condition", new_callable=PropertyMock)
@patch(f"{PROTOCOL_MODULE}.Hcc003v1.in_numerator")
@patch(f"{PROTOCOL_MODULE}.Hcc003v1.in_denominator")
def test_compute_due_for_eye_and_renal_combines_narratives_and_recommendations(
    in_denominator: MagicMock,
    in_numerator: MagicMock,
    eye: PropertyMock,
    neuro: PropertyMock,
    renal: PropertyMock,
    circ: PropertyMock,
    other: PropertyMock,
    patient_cls: MagicMock,
) -> None:
    """Two matching categories produce two narrative lines and two recommendations."""
    in_denominator.return_value = True
    in_numerator.return_value = True
    eye.return_value = True
    neuro.return_value = False
    renal.return_value = True
    circ.return_value = False
    other.return_value = False
    patient_cls.objects.get.return_value = MagicMock(first_name="Jim")

    effects = _make_protocol().compute()

    data = json.loads(effects[0].payload)["data"]
    assert data["status"] == ProtocolCard.Status.DUE.value
    assert data["narrative"] == (
        "Jim has Diabetes without complications AND "
        "an eye condition commonly caused by diabetes on the Conditions list.\n"
        "Jim has Diabetes without complications AND "
        "a chronic renal condition commonly caused by diabetes on the Conditions list."
    )
    titles = [rec["title"] for rec in data["recommendations"]]
    assert titles == [
        (
            "Consider updating the Diabetes without complications (E11.9) "
            "to Diabetes with secondary eye disease as clinically appropriate."
        ),
        (
            "Consider updating the Diabetes without complications (E11.9) "
            "to Diabetes with secondary renal disease as clinically appropriate."
        ),
    ]
