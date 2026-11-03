"""Patient resolution for the events the protocol responds to."""

import json
from typing import Any

import pytest
from canvas_generated.messages.events_pb2 import Event as EventRequest
from canvas_sdk.events import Event, EventType
from canvas_sdk.test_utils.factories import PatientFactory, ProtocolOverrideFactory
from protocols.hcc005v1_annual_wellness_visit import Hcc005v1

MISSING_ID = "00000000000000000000000000000000"
PROTOCOLS = (Hcc005v1,)

# Events the SDK lookup does not map yet; the protocol takes their patient from the context.
CONTEXT_PATIENT_EVENTS = (
    "BILLING_LINE_ITEM_CREATED",
    "BILLING_LINE_ITEM_UPDATED",
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
    """A protocol override event with no event context resolves to the override's patient."""
    override = ProtocolOverrideFactory.create()
    protocol = _protocol(Hcc005v1, EventType.PROTOCOL_OVERRIDE_UPDATED, str(override.id))
    assert protocol.patient_id_from_target() == str(override.patient.id)


@pytest.mark.parametrize(
    ("protocol_class", "event_name"),
    [
        (protocol_class, name)
        for protocol_class in PROTOCOLS
        for name in protocol_class.RESPONDS_TO
        if not name.startswith("PATIENT_") and name not in CONTEXT_PATIENT_EVENTS
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
    protocol = _protocol(Hcc005v1, EventType.PATIENT_UPDATED, str(patient.id))
    assert protocol.patient_id_from_target() == str(patient.id)


@pytest.mark.parametrize("event_name", CONTEXT_PATIENT_EVENTS)
def test_billing_line_item_events_take_the_patient_from_the_context(
    event_name: str,
) -> None:
    """Billing line item events resolve the patient from the event context."""
    protocol = _protocol(
        Hcc005v1, EventType.Value(event_name), "record-1", {"patient": {"id": "patient-1"}}
    )
    assert protocol.patient_id_from_target() == "patient-1"


@pytest.mark.parametrize("event_name", CONTEXT_PATIENT_EVENTS)
def test_sdk_lookup_rejects_billing_line_item_events(event_name: str) -> None:
    """Tripwire for the context override in ``__init__``.

    When this fails, the plugin's SDK resolves these events
    (https://github.com/canvas-medical/canvas-plugins/pull/1975): delete the override,
    CONTEXT_PATIENT_EVENTS, and the two tests that use it.
    """
    protocol = _protocol(Hcc005v1, EventType.Value(event_name), MISSING_ID)
    with pytest.raises(ValueError, match="not supported"):
        protocol.patient_id_from_target()
