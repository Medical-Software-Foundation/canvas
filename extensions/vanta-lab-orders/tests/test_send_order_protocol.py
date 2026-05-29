"""Unit tests for vanta_lab_orders.protocols.send_order.SendVantaOrder.

The HTTP layer (lkcareevolve_client) is mocked with pytest-mock.
Canvas SDK data models are created via test-utils factories.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from canvas_sdk.test_utils.factories import (
    CanvasUserFactory,
    LabOrderFactory,
    LabTestFactory,
    NoteFactory,
    PracticeLocationFactory,
    StaffFactory,
)

from tests.conftest import LOCATION_UUID_1
from vanta_lab_orders.protocols.send_order import SendVantaOrder


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_location(location_uuid: str = LOCATION_UUID_1) -> Any:
    """Create a PracticeLocation with the given valid UUID string."""
    return PracticeLocationFactory.create(id=location_uuid, full_name="Main Clinic")


def _make_lab_order(location_uuid: str = LOCATION_UUID_1) -> Any:
    location = _make_location(location_uuid)
    note = NoteFactory.create(location=location)
    lab_order = LabOrderFactory.create(
        note=note,
        patient=note.patient,
        ordering_provider=StaffFactory.create(),
        committer=CanvasUserFactory.create(),
    )
    LabTestFactory.create(order=lab_order)
    return lab_order


def _make_event(lab_order: Any, partner_name: str = "Vanta Diagnostics") -> MagicMock:
    """Build a mock Canvas event for LAB_ORDER_COMMAND__POST_COMMIT."""
    event = MagicMock()
    event.context = {
        "fields": {
            "lab_partner": {"text": partner_name, "value": partner_name},
            "tests": [],
            "ordering_provider": {},
            "diagnosis": [],
            "fasting_status": False,
            "comment": "",
        },
        "note": {"uuid": str(lab_order.note.id)},
        "patient": {"id": str(lab_order.patient.id)},
    }
    event.target.id = str(lab_order.id)
    return event


def _make_secrets(
    partner_name: str = "Vanta Diagnostics",
    location_uuid: str = LOCATION_UUID_1,
    account: str = "ACCT-001",
) -> dict[str, str]:
    return {
        "LKCAREEVOLVE_BASE_URL": "https://lkcareevolve.example.com",
        "LKCAREEVOLVE_API_KEY": "test-key",
        "VANTA_LAB_PARTNER_NAME": partner_name,
        "LOCATION_TO_ACCOUNT_MAP_JSON": json.dumps({location_uuid: account}),
        "SENDING_FACILITY_NAME": "Example Facility",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_non_vanta_partner_returns_empty_no_http_call(mocker: Any) -> None:
    """Non-Vanta lab partner → silent no-op, no HTTP call made."""
    mock_post = mocker.patch("vanta_lab_orders.protocols.send_order.post_order")

    lab_order = _make_lab_order()
    event = _make_event(lab_order, partner_name="Quest Diagnostics")
    secrets = _make_secrets(partner_name="Vanta Diagnostics")

    handler = SendVantaOrder(event=event, secrets=secrets)
    effects = handler.compute()

    assert effects == []
    mock_post.assert_not_called()


@pytest.mark.django_db
def test_vanta_partner_calls_lkcareevolve_with_expected_payload(mocker: Any) -> None:
    """Vanta partner → build_order_payload called and post_order invoked once."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_post = mocker.patch(
        "vanta_lab_orders.protocols.send_order.post_order",
        return_value=mock_response,
    )

    lab_order = _make_lab_order()
    event = _make_event(lab_order, partner_name="Vanta Diagnostics")
    secrets = _make_secrets(partner_name="Vanta Diagnostics")

    handler = SendVantaOrder(event=event, secrets=secrets)
    effects = handler.compute()

    assert effects == []
    mock_post.assert_called_once()

    call_kwargs = mock_post.call_args
    payload_arg = call_kwargs.args[0]
    assert "MessageHeader" in payload_arg
    assert payload_arg["MessageHeader"]["PlacerOrderNumber"] == str(lab_order.id)
    assert payload_arg["MessageHeader"]["SendingFacilityName"] == "Example Facility"


@pytest.mark.django_db
def test_vanta_partner_passes_correct_credentials(mocker: Any) -> None:
    """Correct base_url and api_key are forwarded to post_order."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_post = mocker.patch(
        "vanta_lab_orders.protocols.send_order.post_order",
        return_value=mock_response,
    )

    lab_order = _make_lab_order()
    event = _make_event(lab_order)
    secrets = _make_secrets()

    handler = SendVantaOrder(event=event, secrets=secrets)
    handler.compute()

    call_args = mock_post.call_args
    assert call_args.args[1] == "https://lkcareevolve.example.com"
    assert call_args.args[2] == "test-key"


@pytest.mark.django_db
def test_lkcareevolve_5xx_propagates_exception(mocker: Any) -> None:
    """Non-2xx from LKCareEvolve propagates (fail loud — no swallow)."""

    class FakeHTTPError(Exception):
        pass

    mocker.patch(
        "vanta_lab_orders.protocols.send_order.post_order",
        side_effect=FakeHTTPError("500 Server Error"),
    )

    lab_order = _make_lab_order()
    event = _make_event(lab_order)
    secrets = _make_secrets()

    handler = SendVantaOrder(event=event, secrets=secrets)
    with pytest.raises(FakeHTTPError):
        handler.compute()


@pytest.mark.django_db
def test_network_error_propagates_exception(mocker: Any) -> None:
    """Network failure (timeout, DNS) propagates — no swallow."""

    class FakeTimeout(Exception):
        pass

    mocker.patch(
        "vanta_lab_orders.protocols.send_order.post_order",
        side_effect=FakeTimeout("timed out"),
    )

    lab_order = _make_lab_order()
    event = _make_event(lab_order)
    secrets = _make_secrets()

    handler = SendVantaOrder(event=event, secrets=secrets)
    with pytest.raises(FakeTimeout):
        handler.compute()


@pytest.mark.django_db
def test_no_signed_lab_order_returns_empty(mocker: Any) -> None:
    """When no committed LabOrder is found on the note, the handler logs an
    error and returns [] (the early-return branch in compute())."""
    mock_post = mocker.patch("vanta_lab_orders.protocols.send_order.post_order")

    # Create a Note + Patient + matching Vanta lab partner secret, but
    # deliberately do NOT create a signed LabOrder under that note. The
    # filter (note__id=..., committer__isnull=False) will return None.
    location = _make_location()
    note = NoteFactory.create(location=location)

    event = MagicMock()
    event.context = {
        "fields": {"lab_partner": {"text": "Vanta Diagnostics"}},
        "note": {"uuid": str(note.id)},
        "patient": {"id": str(note.patient.id)},
    }

    secrets = _make_secrets(partner_name="Vanta Diagnostics")

    handler = SendVantaOrder(event=event, secrets=secrets)
    effects = handler.compute()

    assert effects == []
    mock_post.assert_not_called()


@pytest.mark.django_db
def test_missing_location_account_raises(mocker: Any) -> None:
    """Location not in account map → KeyError propagates."""
    mocker.patch("vanta_lab_orders.protocols.send_order.post_order")

    unmapped_uuid = "99999999-9999-9999-9999-999999999999"
    lab_order = _make_lab_order(location_uuid=unmapped_uuid)
    event = _make_event(lab_order)
    # secrets map only has LOCATION_UUID_1 → no entry for unmapped_uuid
    secrets = _make_secrets()

    handler = SendVantaOrder(event=event, secrets=secrets)
    with pytest.raises(KeyError, match="No LKCareEvolve account number configured"):
        handler.compute()


# ---------------------------------------------------------------------------
# AOE
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_aoe_answers_parsed_from_command_and_sent(mocker: Any) -> None:
    """When the Command carries AOE answers, they reach the posted payload."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_post = mocker.patch(
        "vanta_lab_orders.protocols.send_order.post_order",
        return_value=mock_response,
    )

    location = _make_location()
    note = NoteFactory.create(location=location)
    lab_order = LabOrderFactory.create(
        note=note,
        patient=note.patient,
        ordering_provider=StaffFactory.create(),
        committer=CanvasUserFactory.create(),
    )
    LabTestFactory.create(order=lab_order, ontology_test_code="Derm-ID")

    fake_command = MagicMock()
    fake_command.data = {"aoes|Derm-ID|DERMSOU": "DRMSWB"}
    mocker.patch(
        "vanta_lab_orders.protocols.send_order.Command.objects.get",
        return_value=fake_command,
    )

    event = _make_event(lab_order)
    secrets = _make_secrets()

    handler = SendVantaOrder(event=event, secrets=secrets)
    handler.compute()

    payload_arg = mock_post.call_args.args[0]
    obs = payload_arg["ObservationRequest"][0]
    assert obs["AOE"] == [
        {"SequenceNumber": "1", "Code": "DERMSOU", "Description": "", "Answer": "DRMSWB"}
    ]


@pytest.mark.django_db
def test_missing_command_still_sends_without_aoe(mocker: Any) -> None:
    """If the Command can't be loaded, the order is still sent with empty AOE."""
    from canvas_sdk.v1.data import Command

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_post = mocker.patch(
        "vanta_lab_orders.protocols.send_order.post_order",
        return_value=mock_response,
    )
    mocker.patch(
        "vanta_lab_orders.protocols.send_order.Command.objects.get",
        side_effect=Command.DoesNotExist,
    )

    lab_order = _make_lab_order()
    event = _make_event(lab_order)
    secrets = _make_secrets()

    handler = SendVantaOrder(event=event, secrets=secrets)
    effects = handler.compute()

    assert effects == []
    mock_post.assert_called_once()
    payload_arg = mock_post.call_args.args[0]
    assert payload_arg["ObservationRequest"][0]["AOE"] == []
