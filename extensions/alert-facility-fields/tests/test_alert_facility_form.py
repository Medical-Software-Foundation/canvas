from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from alert_facility_fields.protocols.alert_facility_form import (
    AlertFacilityFormHandler,
    AlertFacilityRequiredValidator,
)


def _make_event(
    schema_key: str | None = None,
    command_uuid: str = "cmd-uuid",
    purpose: str = "form",
) -> SimpleNamespace:
    context: dict[str, Any] = {"purpose": purpose}
    if schema_key is not None:
        context["schema_key"] = schema_key
    return SimpleNamespace(
        context=context,
        target=SimpleNamespace(id=command_uuid),
    )


def _payload(effect: Any) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(effect.payload)["data"]
    return data


# --- AlertFacilityFormHandler -------------------------------------------------


@pytest.fixture
def patched_form_metadata():  # type: ignore[no-untyped-def]
    """Mock CommandMetadata used by AlertFacilityFormHandler. Defaults to no stored value."""
    with patch(
        "alert_facility_fields.protocols.alert_facility_form.CommandMetadata"
    ) as mock:
        mock.objects.filter.return_value.values_list.return_value.first.return_value = None
        yield mock


def _set_form_value(mock_metadata: Any, value: str | None) -> None:
    mock_metadata.objects.filter.return_value.values_list.return_value.first.return_value = value


@pytest.mark.parametrize("schema_key", ["medicationStatement", "stopMedication"])
def test_emits_alert_facility_field_for_supported_commands(
    patched_form_metadata: Any, schema_key: str
) -> None:
    handler = AlertFacilityFormHandler(_make_event(schema_key, command_uuid="abc-123"))

    effects = handler.compute()

    assert len(effects) == 1
    data = _payload(effects[0])
    assert data["command"] == "abc-123"
    assert len(data["form"]) == 1
    field = data["form"][0]
    assert field["key"] == "alert_facility"
    assert field["label"] == "Alert facility"
    assert field["type"] == "select"
    assert field["options"] == ["Yes", "No"]
    assert field["required"] is True
    assert field["editable"] is True
    assert field["value"] is None


@pytest.mark.parametrize(
    "schema_key",
    [
        "plan",
        "assess",
        "diagnose",
        "questionnaire",
        "medication_statement",
        "stop_medication",
        "",
        None,
    ],
)
def test_no_op_for_other_schema_keys(
    patched_form_metadata: Any, schema_key: str | None
) -> None:
    handler = AlertFacilityFormHandler(_make_event(schema_key))

    assert handler.compute() == []
    patched_form_metadata.objects.filter.assert_not_called()


@pytest.mark.parametrize("purpose", ["form", "print"])
def test_same_field_emitted_for_form_and_print_purposes(
    patched_form_metadata: Any, purpose: str
) -> None:
    handler = AlertFacilityFormHandler(_make_event("medicationStatement", purpose=purpose))

    effects = handler.compute()

    assert len(effects) == 1
    data = _payload(effects[0])
    assert [f["key"] for f in data["form"]] == ["alert_facility"]


def test_command_uuid_is_propagated_from_event_target(patched_form_metadata: Any) -> None:
    handler = AlertFacilityFormHandler(_make_event("stopMedication", command_uuid="xyz-789"))

    effects = handler.compute()

    assert _payload(effects[0])["command"] == "xyz-789"


@pytest.mark.parametrize("stored_value", ["Yes", "No"])
def test_field_is_prepopulated_with_existing_metadata_value(
    patched_form_metadata: Any, stored_value: str
) -> None:
    """Reopening a command with stored alert_facility metadata shows the saved choice."""
    _set_form_value(patched_form_metadata, stored_value)
    handler = AlertFacilityFormHandler(_make_event("medicationStatement", command_uuid="abc-123"))

    effects = handler.compute()

    assert len(effects) == 1
    field = _payload(effects[0])["form"][0]
    assert field["value"] == stored_value
    patched_form_metadata.objects.filter.assert_called_once_with(
        command__id="abc-123", key="alert_facility"
    )


def test_field_value_is_none_when_no_metadata_stored(patched_form_metadata: Any) -> None:
    """First-open: no stored value → field renders empty."""
    _set_form_value(patched_form_metadata, None)
    handler = AlertFacilityFormHandler(_make_event("stopMedication"))

    effects = handler.compute()

    field = _payload(effects[0])["form"][0]
    assert field["value"] is None


# --- AlertFacilityRequiredValidator -------------------------------------------


def _validator_event(command_uuid: str = "cmd-uuid") -> SimpleNamespace:
    return SimpleNamespace(
        context={},
        target=SimpleNamespace(id=command_uuid),
    )


@pytest.fixture
def patched_metadata():  # type: ignore[no-untyped-def]
    with patch(
        "alert_facility_fields.protocols.alert_facility_form.CommandMetadata"
    ) as mock:
        yield mock


def _set_first(mock_metadata: Any, value: Any) -> None:
    mock_metadata.objects.filter.return_value.first.return_value = value


def test_validator_emits_error_when_metadata_missing(patched_metadata: Any) -> None:
    _set_first(patched_metadata, None)
    handler = AlertFacilityRequiredValidator(_validator_event(command_uuid="cmd-1"))

    effects = handler.compute()

    assert len(effects) == 1
    payload = json.loads(effects[0].payload)
    assert payload["data"]["errors"] == [{"message": "Alert Facility is a required field."}]
    patched_metadata.objects.filter.assert_called_once_with(
        command__id="cmd-1", key="alert_facility"
    )


@pytest.mark.parametrize("blank_value", ["", "   ", None])
def test_validator_emits_error_when_metadata_blank(
    patched_metadata: Any, blank_value: str | None
) -> None:
    _set_first(patched_metadata, SimpleNamespace(value=blank_value))
    handler = AlertFacilityRequiredValidator(_validator_event())

    effects = handler.compute()

    assert len(effects) == 1
    payload = json.loads(effects[0].payload)
    assert payload["data"]["errors"][0]["message"] == "Alert Facility is a required field."


@pytest.mark.parametrize("value", ["Yes", "No"])
def test_validator_no_op_when_metadata_set(patched_metadata: Any, value: str) -> None:
    _set_first(patched_metadata, SimpleNamespace(value=value))
    handler = AlertFacilityRequiredValidator(_validator_event())

    assert handler.compute() == []
