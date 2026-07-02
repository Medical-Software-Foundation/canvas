"""Tests for the GET /records/<external_id>/linked-patient route.

The Add and open flow lands a patient through an asynchronous create effect, so
the new Canvas patient id is not known when the accept response returns. The
client polls this route until the Salesforce external identifier resolves to a
patient, then opens the chart in the tab it parked. The route drives the same
``find_linked_patient_id`` lookup the modify and delete paths use, exercised
here directly against the SDK Patient ORM.
"""

from __future__ import annotations

import json
from base64 import b64decode
from datetime import date, timedelta
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock, PropertyMock

from canvas_sdk.test_utils.factories import PatientFactory
from canvas_sdk.v1.data.patient import PatientExternalIdentifier

from salesforce_to_canvas_integration.handlers.status_api import SalesforceStatusAPI


def _make_api() -> SalesforceStatusAPI:
    handler = SalesforceStatusAPI.__new__(SalesforceStatusAPI)
    handler.event = MagicMock()
    handler.secrets = {}
    handler.environment = {}
    handler._handler = None
    handler._path_pattern = None
    return handler


def _request(external_id: str) -> MagicMock:
    request = MagicMock()
    request.path_params = {"external_id": external_id}
    return request


def _drive(api: SalesforceStatusAPI, request: MagicMock) -> list[Any]:
    type(api).request = PropertyMock(return_value=request)
    return api.linked_patient()


def _status(effect: Any) -> int:
    return int(json.loads(effect.payload)["status_code"])


def _json_body(effect: Any) -> dict[str, Any]:
    payload = json.loads(effect.payload)
    return json.loads(b64decode(payload["body"]).decode())


def _link_patient(external_id: str) -> Any:
    """Create a Canvas patient carrying a matching Salesforce external identifier."""
    patient = PatientFactory.create()
    today = date.today()
    PatientExternalIdentifier.objects.create(
        patient=patient,
        use="official",
        identifier_type="external",
        system="salesforce",
        value=external_id,
        issued_date=today,
        expiration_date=today + timedelta(days=365),
    )
    return patient


def test_linked_patient_returns_patient_id_when_linked() -> None:
    """A resolved Salesforce identifier returns the Canvas patient id."""
    patient = _link_patient("00QLEAD777")

    responses = _drive(_make_api(), _request("00QLEAD777"))

    assert _status(responses[0]) == HTTPStatus.OK
    assert _json_body(responses[0]) == {"patient_id": str(patient.id)}


def test_linked_patient_returns_empty_when_not_linked_yet() -> None:
    """Before the create effect lands, the lookup returns an empty patient id."""
    responses = _drive(_make_api(), _request("00QLEAD_PENDING"))

    assert _status(responses[0]) == HTTPStatus.OK
    assert _json_body(responses[0]) == {"patient_id": ""}


def _drive_canvas_current(api: SalesforceStatusAPI, request: MagicMock) -> list[Any]:
    type(api).request = PropertyMock(return_value=request)
    return api.canvas_current()


def test_canvas_current_returns_patient_id_and_demographics_when_linked() -> None:
    """A linked record returns the live chart demographics for the comparison."""
    patient = _link_patient("00QCURR777")

    responses = _drive_canvas_current(_make_api(), _request("00QCURR777"))

    assert _status(responses[0]) == HTTPStatus.OK
    body = _json_body(responses[0])
    assert body["patient_id"] == str(patient.id)
    # The snapshot carries the chart name, the now side of the Records comparison.
    assert body["canvas"]["first_name"] == patient.first_name
    assert body["canvas"]["last_name"] == patient.last_name


def test_canvas_current_returns_empty_snapshot_when_not_linked() -> None:
    """An unlinked record draws no comparison, so the snapshot comes back empty."""
    responses = _drive_canvas_current(_make_api(), _request("00QCURR_NONE"))

    assert _status(responses[0]) == HTTPStatus.OK
    assert _json_body(responses[0]) == {"patient_id": "", "canvas": {}}
