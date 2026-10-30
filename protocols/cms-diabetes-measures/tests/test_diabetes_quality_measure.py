"""Tests for the shared DiabetesQualityMeasure base class and event subscriptions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from canvas_sdk.events import EventType
from protocols.cms123v6_diabetes_foot_exam import ClinicalQualityMeasure123v6
from protocols.cms131v6_diabetes_eye_exam import ClinicalQualityMeasure131v6
from protocols.cms134v6_diabetes_medical_attention_for_nephropathy import (
    ClinicalQualityMeasure134v6,
)


def _protocol(context: dict) -> ClinicalQualityMeasure123v6:
    """A foot-exam protocol for an event the SDK can't map to a patient."""
    event = MagicMock()
    event.type = EventType.INTERVIEW_UPDATED
    event.target.id = "interview-1"
    event.context = context
    return ClinicalQualityMeasure123v6(event=event)


def test_resolve_patient_id_falls_back_to_event_context() -> None:
    """Interview/instruction/referral-report events carry the patient in the context."""
    protocol = _protocol({"patient": {"id": "patient-1"}})
    with patch.object(
        ClinicalQualityMeasure123v6,
        "patient_id_from_target",
        side_effect=ValueError("unsupported"),
    ):
        assert protocol.resolve_patient_id() == "patient-1"
    assert protocol._patient_id == "patient-1"


def test_resolve_patient_id_reraises_without_context_patient() -> None:
    """No patient in the context means the event is genuinely unsupported."""
    protocol = _protocol({})
    with (
        patch.object(
            ClinicalQualityMeasure123v6,
            "patient_id_from_target",
            side_effect=ValueError("unsupported"),
        ),
        pytest.raises(ValueError, match="unsupported"),
    ):
        protocol.resolve_patient_id()


def test_resolve_patient_id_prefers_target_lookup() -> None:
    """Supported events resolve through the SDK lookup."""
    protocol = _protocol({"patient": {"id": "from-context"}})
    with patch.object(
        ClinicalQualityMeasure123v6, "patient_id_from_target", return_value="from-target"
    ):
        assert protocol.resolve_patient_id() == "from-target"


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
    protocol = _protocol({})
    with (
        patch.object(ClinicalQualityMeasure123v6, "resolve_patient_id", return_value="p-1"),
        patch("protocols.diabetes_quality_measure.Patient") as patient_cls,
    ):
        assert protocol.patient is protocol.patient
    patient_cls.objects.get.assert_called_once_with(id="p-1")
