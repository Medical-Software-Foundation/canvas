"""Tests for the CCP004v1 — Diagnosis Of Diabetes protocol plugin."""

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from canvas_sdk.effects.protocol_card import ProtocolCard
from canvas_sdk.events import EventType
from protocols.ccp004v1_diabetes import Ccp004v1


PROTOCOL_MODULE = "protocols.ccp004v1_diabetes"
MANIFEST_PATH = Path(__file__).resolve().parents[1] / "CANVAS_MANIFEST.json"


def _event(
    patient_id: str | None = "patient-123",
    target_id: str = "condition-id",
) -> SimpleNamespace:
    """Build a minimal event stub, optionally carrying a patient in its context."""
    context: dict[str, Any] = {}
    if patient_id is not None:
        context["patient"] = {"id": patient_id}
    return SimpleNamespace(
        type=EventType.CONDITION_UPDATED,
        target=SimpleNamespace(id=target_id),
        context=context,
    )


@pytest.fixture
def protocol() -> Ccp004v1:
    """Return a Ccp004v1 built from a CONDITION_UPDATED event for ``patient-123``."""
    return Ccp004v1(event=_event())


def _condition(onset: date | None) -> SimpleNamespace:
    """Build a stand-in for a Condition with an ``onset_date`` attribute."""
    return SimpleNamespace(onset_date=onset)


def _stub_condition_objects(*results: list[Any]) -> tuple[Any, MagicMock, MagicMock]:
    """Build a Condition.objects stub whose queryset chain yields ``results`` per access.

    Each element of ``results`` is what one evaluation of the chain returns, so a
    property that re-queries sees a different list on each access.
    """
    order_by = MagicMock(side_effect=[iter(result) for result in results])
    active = MagicMock(return_value=SimpleNamespace(order_by=order_by))
    find = MagicMock(return_value=SimpleNamespace(active=active))
    for_patient = MagicMock(return_value=SimpleNamespace(find=find))
    return SimpleNamespace(for_patient=for_patient), for_patient, order_by


def _manifest_protocol_meta() -> dict[str, Any]:
    """The protocol component's ``meta`` block from CANVAS_MANIFEST.json."""
    manifest = json.loads(MANIFEST_PATH.read_text())
    return manifest["components"]["protocols"][0]["meta"]


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


def test_manifest_shows_card_in_chart() -> None:
    """Chart visibility is on, matching the legacy built-in's fleet behavior.

    The installer reads show_in_chart from CANVAS_MANIFEST.json, not from the
    Meta class, so the manifest is the value that has to be True.
    """
    assert _manifest_protocol_meta()["show_in_chart"] is True


def test_manifest_meta_matches_protocol_meta() -> None:
    """The manifest's descriptive meta stays in sync with the protocol's Meta class."""
    manifest_meta = _manifest_protocol_meta()
    for field in (
        "title",
        "version",
        "description",
        "information",
        "identifiers",
        "types",
        "authors",
        "references",
        "default_permission_flags",
    ):
        assert manifest_meta[field] == getattr(Ccp004v1.Meta, field), field


def test_responds_to_condition_events() -> None:
    """Protocol responds to the condition lifecycle event types."""
    assert set(Ccp004v1.RESPONDS_TO) == {
        EventType.Name(EventType.CONDITION_CREATED),
        EventType.Name(EventType.CONDITION_UPDATED),
        EventType.Name(EventType.CONDITION_ASSESSED),
        EventType.Name(EventType.CONDITION_RESOLVED),
    }


def test_init_takes_patient_id_from_event_context() -> None:
    """A patient in the event context is used directly, avoiding the target lookup."""
    instance = Ccp004v1(event=_event(patient_id="patient-abc"))

    assert instance._patient_id == "patient-abc"
    assert instance.patient_id_from_target() == "patient-abc"


def test_init_defers_to_target_lookup_without_patient_context() -> None:
    """Without a patient in context, _patient_id is left unset for the base class to resolve.

    The condition id from the event target must never be used as the patient id.
    """
    instance = Ccp004v1(event=_event(patient_id=None, target_id="condition-id"))

    assert instance._patient_id is None


def test_active_diabetes_conditions_queries_for_context_patient(protocol: Ccp004v1) -> None:
    """The queryset chains for_patient().find().active().order_by('onset_date')."""
    objects, for_patient, order_by = _stub_condition_objects(["c1", "c2"])

    with patch(f"{PROTOCOL_MODULE}.Condition.objects", new=objects):
        result = protocol.active_diabetes_conditions

    assert result == ["c1", "c2"]
    for_patient.assert_called_once_with("patient-123")
    order_by.assert_called_once_with("onset_date")


def test_active_diabetes_conditions_is_not_cached(protocol: Ccp004v1) -> None:
    """The property re-queries on every access so a newly added condition is picked up."""
    objects, for_patient, _ = _stub_condition_objects([], [_condition(date(2018, 8, 20))])

    with patch(f"{PROTOCOL_MODULE}.Condition.objects", new=objects):
        assert protocol.active_diabetes_conditions == []
        second = protocol.active_diabetes_conditions

    assert for_patient.call_count == 2
    assert [c.onset_date for c in second] == [date(2018, 8, 20)]


def test_date_of_diagnosis_no_conditions(protocol: Ccp004v1) -> None:
    """When the patient has no active diabetes conditions, date_of_diagnosis is ''."""
    with patch.object(
        type(protocol),
        "active_diabetes_conditions",
        new_callable=PropertyMock,
        return_value=[],
    ):
        assert protocol.date_of_diagnosis == ""


def test_date_of_diagnosis_single_condition(protocol: Ccp004v1) -> None:
    """A single active diabetes condition yields its onset date in ISO format."""
    with patch.object(
        type(protocol),
        "active_diabetes_conditions",
        new_callable=PropertyMock,
        return_value=[_condition(date(2018, 8, 20))],
    ):
        assert protocol.date_of_diagnosis == "2018-08-20"


def test_date_of_diagnosis_multiple_returns_oldest(protocol: Ccp004v1) -> None:
    """Multiple active conditions return the earliest onset (order_by handles sorting)."""
    conditions = [
        _condition(date(2018, 8, 17)),
        _condition(date(2018, 8, 18)),
        _condition(date(2018, 8, 19)),
    ]
    with patch.object(
        type(protocol),
        "active_diabetes_conditions",
        new_callable=PropertyMock,
        return_value=conditions,
    ):
        assert protocol.date_of_diagnosis == "2018-08-17"


def test_date_of_diagnosis_skips_conditions_without_onset(protocol: Ccp004v1) -> None:
    """Conditions missing onset_date are skipped so the next available date wins."""
    conditions = [_condition(None), _condition(date(2019, 1, 5))]
    with patch.object(
        type(protocol),
        "active_diabetes_conditions",
        new_callable=PropertyMock,
        return_value=conditions,
    ):
        assert protocol.date_of_diagnosis == "2019-01-05"


def test_in_initial_population(protocol: Ccp004v1) -> None:
    """All patients are in the initial population."""
    assert protocol.in_initial_population() is True


def test_in_denominator(protocol: Ccp004v1) -> None:
    """All patients are in the denominator."""
    assert protocol.in_denominator() is True


def test_in_numerator_false_when_no_conditions(protocol: Ccp004v1) -> None:
    """in_numerator is False when there are no active diabetes conditions."""
    with patch.object(
        type(protocol),
        "active_diabetes_conditions",
        new_callable=PropertyMock,
        return_value=[],
    ):
        assert protocol.in_numerator() is False


def test_in_numerator_true_with_active_condition(protocol: Ccp004v1) -> None:
    """in_numerator is True when there is an active diabetes condition with an onset."""
    with patch.object(
        type(protocol),
        "active_diabetes_conditions",
        new_callable=PropertyMock,
        return_value=[_condition(date(2018, 8, 20))],
    ):
        assert protocol.in_numerator() is True


def _compute(
    protocol: Ccp004v1, *, in_denominator: bool, diagnosis: str
) -> tuple[list[Any], MagicMock]:
    """Run compute() with the population predicates and diagnosis date stubbed out.

    Returns the emitted effects along with the patched ``Patient.objects.get``.
    """
    with (
        patch.object(type(protocol), "in_denominator", return_value=in_denominator),
        patch.object(type(protocol), "in_numerator", return_value=bool(diagnosis)),
        patch.object(
            type(protocol),
            "date_of_diagnosis",
            new_callable=PropertyMock,
            return_value=diagnosis,
        ),
        patch(
            f"{PROTOCOL_MODULE}.Patient.objects.get",
            return_value=SimpleNamespace(first_name="Nicolas"),
        ) as patient_get,
    ):
        return protocol.compute(), patient_get


def test_compute_not_in_denominator_returns_no_effects(protocol: Ccp004v1) -> None:
    """When a patient is not in the denominator, no effects are emitted and no patient is read."""
    effects, patient_get = _compute(protocol, in_denominator=False, diagnosis="2017-03-14")

    assert effects == []
    patient_get.assert_not_called()


def test_compute_in_denominator_not_in_numerator_is_satisfied(protocol: Ccp004v1) -> None:
    """A non-diabetic patient gets a satisfied card with no recommendations."""
    effects, _ = _compute(protocol, in_denominator=True, diagnosis="")

    assert len(effects) == 1
    payload = json.loads(effects[0].payload)
    assert payload["patient"] == "patient-123"
    assert payload["key"] == "CCP004v1"
    assert payload["data"]["title"] == "Diagnosis Of Diabetes"
    assert payload["data"]["narrative"] == "Nicolas has not been diagnosed of diabetes."
    assert payload["data"]["status"] == ProtocolCard.Status.SATISFIED.value
    assert payload["data"]["due_in"] == -1
    assert payload["data"]["recommendations"] == []


def test_compute_in_denominator_in_numerator_is_due(protocol: Ccp004v1) -> None:
    """A diabetic patient gets a due card whose narrative carries the formatted onset date."""
    effects, _ = _compute(protocol, in_denominator=True, diagnosis="2017-03-14")

    assert len(effects) == 1
    payload = json.loads(effects[0].payload)
    assert (
        payload["data"]["narrative"]
        == "Nicolas has been diagnosed of diabetes on Tue, Mar 14th 2017."
    )
    assert payload["data"]["status"] == ProtocolCard.Status.DUE.value
    assert payload["data"]["due_in"] == 0


def test_compute_recommends_originating_a_follow_up_command(protocol: Ccp004v1) -> None:
    """The recommendation inserts a Follow Up command rather than the legacy 'schedule' type."""
    effects, _ = _compute(protocol, in_denominator=True, diagnosis="2017-03-14")

    recommendations = json.loads(effects[0].payload)["data"]["recommendations"]
    assert len(recommendations) == 1
    recommendation = recommendations[0]
    assert recommendation["title"] == "Contact the patient"
    assert recommendation["button"] == "Schedule"
    assert [command["command"]["type"] for command in recommendation["commands"]] == ["followUp"]
    assert recommendation["commands"][0]["context"]["effect_type"] == "ORIGINATE_FOLLOW_UP_COMMAND"
