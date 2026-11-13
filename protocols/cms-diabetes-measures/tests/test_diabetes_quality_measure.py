"""The shared DiabetesQualityMeasure base class and event subscriptions."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from canvas_generated.messages.events_pb2 import Event as EventRequest
from canvas_sdk.events import Event, EventType

from protocols.cms122v6_diabetes_hemoglobin_a1c_poor_control import ClinicalQualityMeasure122v6
from protocols.cms131v6_diabetes_eye_exam import ClinicalQualityMeasure131v6
from protocols.cms951v5_kidney_health_evaluation import ClinicalQualityMeasure951v5


@pytest.mark.parametrize(
    ("protocol_class", "event_types"),
    [
        (ClinicalQualityMeasure122v6, ("LAB_REPORT_CREATED", "LAB_REPORT_UPDATED")),
        (ClinicalQualityMeasure131v6, ("REFERRAL_REPORT_CREATED", "REFERRAL_REPORT_UPDATED")),
        (ClinicalQualityMeasure951v5, ("LAB_REPORT_CREATED", "LAB_REPORT_UPDATED")),
    ],
)
def test_responds_to_events_that_satisfy_the_measure(protocol_class, event_types) -> None:  # noqa: ANN001
    """The card recomputes when the data that satisfies the measure arrives."""
    for event_type in event_types:
        assert event_type in protocol_class.RESPONDS_TO


@pytest.mark.parametrize(
    "protocol_class",
    [ClinicalQualityMeasure122v6, ClinicalQualityMeasure131v6, ClinicalQualityMeasure951v5],
)
def test_responds_to_events_that_change_an_exclusion(protocol_class) -> None:  # noqa: ANN001
    """Billing, conditions, instructions and questionnaires can each add an exclusion."""
    for event_type in (
        "BILLING_LINE_ITEM_CREATED",
        "CONDITION_CREATED",
        "INSTRUCTION_CREATED",
        "INTERVIEW_CREATED",
    ):
        assert event_type in protocol_class.RESPONDS_TO


def test_patient_is_fetched_once_per_instance() -> None:
    """Repeated ``self.patient`` reads share one query."""
    request = EventRequest(type=EventType.PATIENT_UPDATED, target="p-1", context=json.dumps({}))
    protocol = ClinicalQualityMeasure131v6(event=Event(request))
    with patch("protocols.diabetes_quality_measure.Patient") as patient_cls:
        assert protocol.patient is protocol.patient
    patient_cls.objects.get.assert_called_once_with(id="p-1")
