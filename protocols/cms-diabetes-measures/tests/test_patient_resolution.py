"""Patient resolution for the events the protocol responds to."""

import json
from datetime import date
from typing import Any

import pytest
from canvas_generated.messages.events_pb2 import Event as EventRequest
from canvas_sdk.events import Event, EventType
from canvas_sdk.test_utils.factories import PatientFactory
from canvas_sdk.v1.data.condition import Condition
from protocols.cms122v6_diabetes_hemoglobin_a1c_poor_control import ClinicalQualityMeasure122v6
from protocols.cms123v6_diabetes_foot_exam import ClinicalQualityMeasure123v6
from protocols.cms131v6_diabetes_eye_exam import ClinicalQualityMeasure131v6
from protocols.cms134v6_diabetes_medical_attention_for_nephropathy import (
    ClinicalQualityMeasure134v6,
)

MISSING_ID = "00000000000000000000000000000000"
PROTOCOLS = (
    ClinicalQualityMeasure122v6,
    ClinicalQualityMeasure123v6,
    ClinicalQualityMeasure131v6,
    ClinicalQualityMeasure134v6,
)


def _protocol(
    protocol_class: type,
    event_type: int,
    target: str,
    context: dict[str, Any] | None = None,
) -> Any:
    """Build a protocol for a real SDK event."""
    request = EventRequest(type=event_type, target=target, context=json.dumps(context or {}))
    return protocol_class(event=Event(request))


def test_record_events_resolve_the_targets_patient() -> None:
    """A condition event with no event context resolves to the condition's patient."""
    patient = PatientFactory.create()
    condition = Condition.objects.create(
        patient=patient,
        deleted=False,
        onset_date=date(2020, 1, 1),
        resolution_date=date(2020, 1, 1),
        clinical_status="active",
        notes="",
        surgical=False,
    )
    protocol = _protocol(
        ClinicalQualityMeasure122v6, EventType.CONDITION_CREATED, str(condition.id)
    )
    assert protocol.patient_id_from_target() == str(patient.id)


@pytest.mark.parametrize(
    ("protocol_class", "event_name"),
    [
        (protocol_class, name)
        for protocol_class in PROTOCOLS
        for name in protocol_class.RESPONDS_TO
        if not name.startswith("PATIENT_")
    ],
)
def test_sdk_maps_every_record_event_the_protocol_responds_to(
    protocol_class: type, event_name: str
) -> None:
    """The SDK lookup runs for each record event; an unknown target finds no patient."""
    protocol = _protocol(protocol_class, EventType.Value(event_name), MISSING_ID)
    with pytest.raises(ValueError, match="No patient found"):
        protocol.patient_id_from_target()


def test_patient_events_resolve_from_the_target() -> None:
    """Patient events target the patient itself."""
    patient = PatientFactory.create()
    protocol = _protocol(ClinicalQualityMeasure122v6, EventType.PATIENT_UPDATED, str(patient.id))
    assert protocol.patient_id_from_target() == str(patient.id)
