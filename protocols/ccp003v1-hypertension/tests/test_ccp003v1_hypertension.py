"""Tests for the CCP003v1 Diagnosis Of Hypertension protocol."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from protocols.ccp003v1_hypertension import Ccp003v1


@pytest.fixture
def protocol() -> Ccp003v1:
    """Return a Ccp003v1 instance with a fixed patient id and a minimal event stub."""
    event = SimpleNamespace(type="CONDITION_CREATED", target=SimpleNamespace(id="patient-123"))
    instance = Ccp003v1.__new__(Ccp003v1)
    instance.event = event
    instance._patient_id = "patient-123"
    return instance


def _condition(onset: date | None) -> SimpleNamespace:
    """Build a simple stand-in for a Condition with an onset_date attribute."""
    return SimpleNamespace(onset_date=onset)


def test_meta_description() -> None:
    """The Meta description should match the legacy protocol's description verbatim."""
    assert Ccp003v1.Meta.description == "All patients with Diagnosis Of Hypertension."


def test_meta_information() -> None:
    """The Meta information URL should match the legacy protocol's URL verbatim."""
    assert Ccp003v1.Meta.information == "https://canvas-medical.help.usepylon.com/"


def test_meta_version() -> None:
    """The Meta version should match the legacy protocol's version."""
    assert Ccp003v1.Meta.version == "2020-04-02v1"


def test_meta_identifiers() -> None:
    """The Meta identifiers should be exactly ['CCP003v1']."""
    assert Ccp003v1.Meta.identifiers == ["CCP003v1"]


def test_meta_types() -> None:
    """The Meta types should be exactly ['CCP']."""
    assert Ccp003v1.Meta.types == ["CCP"]


def test_responds_to_condition_events() -> None:
    """RESPONDS_TO should cover the condition lifecycle events."""
    assert set(Ccp003v1.RESPONDS_TO) == {
        "CONDITION_CREATED",
        "CONDITION_UPDATED",
        "CONDITION_ASSESSED",
        "CONDITION_RESOLVED",
    }


def test_in_initial_population_is_true(protocol: Ccp003v1) -> None:
    """All patients are in the initial population."""
    assert protocol.in_initial_population() is True


def test_in_denominator_matches_initial_population(protocol: Ccp003v1) -> None:
    """The denominator mirrors the initial population."""
    assert protocol.in_denominator() is True


def test_date_of_diagnosis_no_conditions(protocol: Ccp003v1) -> None:
    """With no active hypertension conditions, date_of_diagnosis is the empty string."""
    with patch.object(
        type(protocol),
        "active_hypertension_conditions",
        new_callable=PropertyMock,
        return_value=[],
    ):
        assert protocol.date_of_diagnosis == ""


def test_date_of_diagnosis_returns_earliest_onset(protocol: Ccp003v1) -> None:
    """date_of_diagnosis returns the earliest onset_date in ISO format."""
    conditions = [
        _condition(date(2018, 8, 17)),
        _condition(date(2018, 8, 18)),
        _condition(date(2018, 8, 19)),
    ]
    with patch.object(
        type(protocol),
        "active_hypertension_conditions",
        new_callable=PropertyMock,
        return_value=conditions,
    ):
        assert protocol.date_of_diagnosis == "2018-08-17"


def test_date_of_diagnosis_skips_conditions_without_onset(protocol: Ccp003v1) -> None:
    """Conditions missing onset_date are skipped so the next available date wins."""
    conditions = [
        _condition(None),
        _condition(date(2019, 1, 5)),
    ]
    with patch.object(
        type(protocol),
        "active_hypertension_conditions",
        new_callable=PropertyMock,
        return_value=conditions,
    ):
        assert protocol.date_of_diagnosis == "2019-01-05"


def test_in_numerator_true_when_diagnosis_present(protocol: Ccp003v1) -> None:
    """A non-empty date_of_diagnosis puts the patient in the numerator."""
    with patch.object(
        type(protocol),
        "date_of_diagnosis",
        new_callable=PropertyMock,
        return_value="2018-08-17",
    ):
        assert protocol.in_numerator() is True


def test_in_numerator_false_without_diagnosis(protocol: Ccp003v1) -> None:
    """An empty date_of_diagnosis keeps the patient out of the numerator."""
    with patch.object(
        type(protocol),
        "date_of_diagnosis",
        new_callable=PropertyMock,
        return_value="",
    ):
        assert protocol.in_numerator() is False


def test_active_hypertension_conditions_queries_for_patient(protocol: Ccp003v1) -> None:
    """active_hypertension_conditions should chain for_patient().find().active().order_by()."""
    final_qs = MagicMock()
    final_qs.__iter__.return_value = iter(["c1", "c2"])
    order_by = MagicMock(return_value=final_qs)
    active = MagicMock(return_value=SimpleNamespace(order_by=order_by))
    find = MagicMock(return_value=SimpleNamespace(active=active))
    for_patient = MagicMock(return_value=SimpleNamespace(find=find))

    with patch(
        "protocols.ccp003v1_hypertension.Condition.objects",
        new=SimpleNamespace(for_patient=for_patient),
    ):
        result = protocol.active_hypertension_conditions

    assert result == ["c1", "c2"]
    for_patient.assert_called_once_with("patient-123")
    order_by.assert_called_once_with("onset_date")


def test_compute_due_when_diagnosed(protocol: Ccp003v1) -> None:
    """When in numerator, compute emits a DUE protocol card with a recommendation."""
    patient = SimpleNamespace(first_name="Nicolas")
    with (
        patch.object(type(protocol), "in_denominator", return_value=True),
        patch.object(type(protocol), "in_numerator", return_value=True),
        patch.object(
            type(protocol),
            "date_of_diagnosis",
            new_callable=PropertyMock,
            return_value="2017-03-14",
        ),
        patch(
            "protocols.ccp003v1_hypertension.Patient.objects.get",
            return_value=patient,
        ),
    ):
        effects = protocol.compute()

    assert len(effects) == 1
    assert "Nicolas has been diagnosed of hypertension on Tue, Mar 14th 2017." in effects[0].payload
    assert "due" in effects[0].payload


def test_compute_satisfied_when_not_diagnosed(protocol: Ccp003v1) -> None:
    """When not in numerator but in denominator, compute emits a SATISFIED protocol card."""
    patient = SimpleNamespace(first_name="Nicolas")
    with (
        patch.object(type(protocol), "in_denominator", return_value=True),
        patch.object(type(protocol), "in_numerator", return_value=False),
        patch.object(
            type(protocol),
            "date_of_diagnosis",
            new_callable=PropertyMock,
            return_value="",
        ),
        patch(
            "protocols.ccp003v1_hypertension.Patient.objects.get",
            return_value=patient,
        ),
    ):
        effects = protocol.compute()

    assert len(effects) == 1
    assert "Nicolas has not been diagnosed of hypertension." in effects[0].payload
    assert "satisfied" in effects[0].payload


def test_compute_returns_empty_list_when_not_in_denominator(protocol: Ccp003v1) -> None:
    """When not in the denominator, compute returns no effects."""
    with patch.object(type(protocol), "in_denominator", return_value=False):
        assert protocol.compute() == []
