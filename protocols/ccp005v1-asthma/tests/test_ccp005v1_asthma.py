"""Tests for the CCP005v1 Diagnosis Of Asthma protocol."""

import datetime
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from canvas_sdk.value_set.v2022.condition import Asthma

from protocols.ccp005v1_asthma import Ccp005v1


def make_protocol(monkeypatch: pytest.MonkeyPatch, patient_id: str = "patient-1") -> Ccp005v1:
    """Build a Ccp005v1 instance with patient_id_from_target stubbed."""
    protocol = Ccp005v1.__new__(Ccp005v1)
    monkeypatch.setattr(Ccp005v1, "patient_id_from_target", lambda self: patient_id)
    return protocol


def test_meta_attributes() -> None:
    """Meta carries the expected identifiers, description, and type."""
    assert Ccp005v1.Meta.title == "Diagnosis Of Asthma"
    assert Ccp005v1.Meta.description == "All patients with Diagnosis Of Asthma."
    assert Ccp005v1.Meta.identifiers == ["CCP005v1"]
    assert Ccp005v1.Meta.types == ["CCP"]
    assert Ccp005v1.Meta.version == "2020-04-02v1"
    assert Ccp005v1.Meta.information == "https://canvas-medical.help.usepylon.com/"
    assert Ccp005v1.Meta.show_in_chart is False


def test_responds_to_condition_events() -> None:
    """The protocol subscribes to condition lifecycle events."""
    assert "CONDITION_CREATED" in Ccp005v1.RESPONDS_TO
    assert "CONDITION_UPDATED" in Ccp005v1.RESPONDS_TO
    assert "CONDITION_ASSESSED" in Ccp005v1.RESPONDS_TO
    assert "CONDITION_RESOLVED" in Ccp005v1.RESPONDS_TO


def test_in_initial_population_is_true(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every patient is in the initial population."""
    protocol = make_protocol(monkeypatch)
    assert protocol.in_initial_population() is True


def test_in_denominator_matches_initial_population(monkeypatch: pytest.MonkeyPatch) -> None:
    """The denominator mirrors the initial population."""
    protocol = make_protocol(monkeypatch)
    assert protocol.in_denominator() is True


def test_date_of_diagnosis_no_conditions(monkeypatch: pytest.MonkeyPatch) -> None:
    """No active asthma conditions yields an empty diagnosis date."""
    protocol = make_protocol(monkeypatch)
    monkeypatch.setattr(
        Ccp005v1,
        "active_asthma_conditions",
        PropertyMock(return_value=[]),
    )
    assert protocol.date_of_diagnosis == ""


def test_date_of_diagnosis_returns_earliest_onset(monkeypatch: pytest.MonkeyPatch) -> None:
    """The oldest condition's onset is returned (active_asthma_conditions is ordered)."""
    protocol = make_protocol(monkeypatch)
    conditions = [
        SimpleNamespace(onset_date=datetime.date(2018, 8, 17)),
        SimpleNamespace(onset_date=datetime.date(2018, 8, 18)),
        SimpleNamespace(onset_date=datetime.date(2018, 8, 19)),
    ]
    monkeypatch.setattr(
        Ccp005v1,
        "active_asthma_conditions",
        PropertyMock(return_value=conditions),
    )
    assert protocol.date_of_diagnosis == "2018-08-17"


def test_date_of_diagnosis_skips_missing_onset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Conditions without an onset_date are skipped."""
    protocol = make_protocol(monkeypatch)
    conditions = [
        SimpleNamespace(onset_date=None),
        SimpleNamespace(onset_date=datetime.date(2020, 1, 1)),
    ]
    monkeypatch.setattr(
        Ccp005v1,
        "active_asthma_conditions",
        PropertyMock(return_value=conditions),
    )
    assert protocol.date_of_diagnosis == "2020-01-01"


def test_in_numerator_true_when_date(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-empty diagnosis date puts the patient in the numerator."""
    protocol = make_protocol(monkeypatch)
    monkeypatch.setattr(
        Ccp005v1,
        "date_of_diagnosis",
        PropertyMock(return_value="2017-03-14"),
    )
    assert protocol.in_numerator() is True


def test_in_numerator_false_when_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty diagnosis date excludes the patient from the numerator."""
    protocol = make_protocol(monkeypatch)
    monkeypatch.setattr(
        Ccp005v1,
        "date_of_diagnosis",
        PropertyMock(return_value=""),
    )
    assert protocol.in_numerator() is False


def test_compute_due_when_diagnosed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A patient with an asthma diagnosis gets a Due card with a contact recommendation."""
    protocol = make_protocol(monkeypatch)
    monkeypatch.setattr(
        Ccp005v1,
        "date_of_diagnosis",
        PropertyMock(return_value="2017-03-14"),
    )
    fake_patient = SimpleNamespace(first_name="Nicolas")
    with patch(
        "protocols.ccp005v1_asthma.Patient.objects.get",
        return_value=fake_patient,
    ):
        effects = protocol.compute()

    assert len(effects) == 1
    payload = json.loads(effects[0].payload)
    assert payload["data"]["status"] == "due"
    assert payload["data"]["due_in"] == 0
    assert (
        payload["data"]["narrative"]
        == "Nicolas has been diagnosed of asthma on Tue, Mar 14th 2017."
    )
    recommendations = payload["data"]["recommendations"]
    assert len(recommendations) == 1
    assert recommendations[0]["title"] == "Contact the patient"
    assert recommendations[0]["button"] == "Schedule"
    assert recommendations[0]["commands"][0]["command"]["type"] == "schedule"


def test_compute_satisfied_when_not_diagnosed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A patient without an asthma diagnosis gets a Satisfied card and no recommendations."""
    protocol = make_protocol(monkeypatch)
    monkeypatch.setattr(
        Ccp005v1,
        "date_of_diagnosis",
        PropertyMock(return_value=""),
    )
    fake_patient = SimpleNamespace(first_name="Nicolas")
    with patch(
        "protocols.ccp005v1_asthma.Patient.objects.get",
        return_value=fake_patient,
    ):
        effects = protocol.compute()

    assert len(effects) == 1
    payload = json.loads(effects[0].payload)
    assert payload["data"]["status"] == "satisfied"
    assert payload["data"]["due_in"] == -1
    assert payload["data"]["narrative"] == "Nicolas has not been diagnosed of asthma."
    assert payload["data"]["recommendations"] == []


def test_compute_returns_empty_when_not_in_denominator(monkeypatch: pytest.MonkeyPatch) -> None:
    """No effects are emitted when the patient is not in the denominator."""
    protocol = make_protocol(monkeypatch)
    monkeypatch.setattr(Ccp005v1, "in_denominator", lambda self: False)
    assert protocol.compute() == []


def test_active_asthma_conditions_calls_for_patient_find_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """active_asthma_conditions chains for_patient -> find(Asthma) -> active -> order_by."""
    protocol = make_protocol(monkeypatch, patient_id="patient-123")

    ordered = MagicMock(name="ordered")
    ordered.__iter__ = lambda self: iter([])
    active = MagicMock(name="active")
    active.order_by.return_value = ordered
    found = MagicMock(name="found")
    found.active.return_value = active
    for_patient = MagicMock(name="for_patient")
    for_patient.find.return_value = found
    manager = MagicMock(name="manager")
    manager.for_patient.return_value = for_patient

    with patch("protocols.ccp005v1_asthma.Condition.objects", manager):
        result = protocol.active_asthma_conditions

    assert result == []
    manager.for_patient.assert_called_once_with("patient-123")
    for_patient.find.assert_called_once_with(Asthma)
    found.active.assert_called_once_with()
    active.order_by.assert_called_once_with("onset_date")
