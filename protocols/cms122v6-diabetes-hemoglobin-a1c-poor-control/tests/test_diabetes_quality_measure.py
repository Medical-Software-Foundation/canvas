"""The DiabetesQualityMeasure base class and event subscriptions."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from canvas_generated.messages.events_pb2 import Event as EventRequest
from canvas_sdk.events import Event, EventType

from protocols.cms122v6_diabetes_hemoglobin_a1c_poor_control import ClinicalQualityMeasure122v6


def test_responds_to_events_that_satisfy_the_measure() -> None:
    """The card recomputes when the data that satisfies the measure arrives."""
    for event_type in ("LAB_REPORT_CREATED", "LAB_REPORT_UPDATED"):
        assert event_type in ClinicalQualityMeasure122v6.RESPONDS_TO


def test_responds_to_events_that_change_an_exclusion() -> None:
    """Billing, conditions, instructions and questionnaires can each add an exclusion."""
    for event_type in (
        "BILLING_LINE_ITEM_CREATED",
        "CONDITION_CREATED",
        "INSTRUCTION_CREATED",
        "INTERVIEW_CREATED",
    ):
        assert event_type in ClinicalQualityMeasure122v6.RESPONDS_TO


def test_patient_is_fetched_once_per_instance() -> None:
    """Repeated ``self.patient`` reads share one query."""
    request = EventRequest(type=EventType.PATIENT_UPDATED, target="p-1", context=json.dumps({}))
    protocol = ClinicalQualityMeasure122v6(event=Event(request))
    with patch("protocols.diabetes_quality_measure.Patient") as patient_cls:
        assert protocol.patient is protocol.patient
    patient_cls.objects.get.assert_called_once_with(id="p-1")


def test_every_copy_of_the_diabetes_base_class_is_identical() -> None:
    """Plugins cannot share code, so each diabetes measure carries a copy; they must not drift apart."""
    copies = sorted(Path(__file__).parents[2].glob("*/protocols/diabetes_quality_measure.py"))
    assert len(copies) >= 3
    digests = {path.parent.parent.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in copies}
    assert len(set(digests.values())) == 1, digests
