import json
from unittest.mock import MagicMock

from canvas_sdk.effects.appointments_metadata import InputType

from patient_state_scheduling.protocols.additional_fields import (
    US_STATES,
    AdditionalFieldsHandler,
)


def test_us_states_complete() -> None:
    """The options cover all 50 states plus DC, with no duplicates."""
    assert len(US_STATES) == 51
    assert len(set(US_STATES)) == 51
    assert "District of Columbia" in US_STATES
    # States referenced by the demo location mapping must be present.
    for state in ("California", "Colorado", "New York", "Kansas", "New Jersey"):
        assert state in US_STATES


def test_compute_returns_single_state_field() -> None:
    """compute() emits one editable, optional SELECT field keyed 'state'."""
    handler = AdditionalFieldsHandler(event=MagicMock())

    effects = handler.compute()

    assert len(effects) == 1
    payload = json.loads(effects[0].payload)
    fields = payload["data"]["form"]
    assert len(fields) == 1

    field = fields[0]
    assert field["key"] == "state"
    assert field["label"] == "Patient's Current State"
    assert field["type"] == InputType.SELECT.value
    assert field["required"] is False
    assert field["editable"] is True
    assert field["options"] == US_STATES
