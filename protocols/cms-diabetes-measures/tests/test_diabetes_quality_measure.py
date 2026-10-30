"""Tests for the shared DiabetesQualityMeasure base class and event subscriptions."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from canvas_generated.messages.events_pb2 import Event as EventRequest
from canvas_sdk.events import Event, EventType
from protocols.cms123v6_diabetes_foot_exam import ClinicalQualityMeasure123v6
from protocols.cms131v6_diabetes_eye_exam import ClinicalQualityMeasure131v6
from protocols.cms134v6_diabetes_medical_attention_for_nephropathy import (
    ClinicalQualityMeasure134v6,
)


def _protocol(event_type: int, target: str, context: dict) -> ClinicalQualityMeasure123v6:
    """A foot-exam protocol for a real SDK event."""
    return ClinicalQualityMeasure123v6(
        event=Event(EventRequest(type=event_type, target=target, context=json.dumps(context)))
    )


def test_patient_id_comes_from_event_context_on_record_events() -> None:
    """Record events resolve the patient from the context, not the SDK's target lookup."""
    protocol = _protocol(
        EventType.CONDITION_CREATED, "condition-1", {"patient": {"id": "patient-1"}}
    )
    assert protocol.patient_id_from_target() == "patient-1"


def test_patient_events_resolve_from_the_target() -> None:
    """Patient events carry no context patient; the target is the patient."""
    protocol = _protocol(EventType.PATIENT_UPDATED, "patient-2", {})
    assert protocol.patient_id_from_target() == "patient-2"


@pytest.mark.parametrize(
    ("protocol_class", "event_types"),
    [
        (ClinicalQualityMeasure123v6, ("INTERVIEW_CREATED", "INTERVIEW_UPDATED")),
        (ClinicalQualityMeasure131v6, ("REFERRAL_REPORT_CREATED", "REFERRAL_REPORT_UPDATED")),
        (ClinicalQualityMeasure134v6, ("REFERRAL_REPORT_CREATED", "REFERRAL_REPORT_UPDATED")),
    ],
)
def test_responds_to_events_that_satisfy_the_measure(protocol_class, event_types) -> None:
    """The card recomputes when the data that satisfies the measure arrives."""
    for event_type in event_types:
        assert event_type in protocol_class.RESPONDS_TO


def test_patient_is_fetched_once_per_instance() -> None:
    """Repeated ``self.patient`` reads share one query."""
    protocol = _protocol(EventType.PATIENT_UPDATED, "p-1", {})
    with patch("protocols.diabetes_quality_measure.Patient") as patient_cls:
        assert protocol.patient is protocol.patient
    patient_cls.objects.get.assert_called_once_with(id="p-1")
