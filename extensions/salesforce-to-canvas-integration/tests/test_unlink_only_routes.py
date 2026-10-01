"""Tests for the Unlink only audit route on SalesforceStatusAPI.

Covers ``POST /records/<external_id>/unlink-only``. The route reads the linked
Canvas patient and drops the Salesforce external identifier via the Canvas
FHIR client. Tests inject a fake client through the
``_build_canvas_fhir_client`` seam so they never reach the SDK ``Http`` import.
"""

import json
from datetime import date, datetime, timedelta, timezone
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock, PropertyMock

import factory
import pytest

from canvas_sdk.test_utils.factories import PatientFactory, StaffFactory
from canvas_sdk.v1.data.patient import PatientExternalIdentifier

from salesforce_to_canvas_integration.handlers.status_api import SalesforceStatusAPI
from salesforce_to_canvas_integration.models.incoming_patient_record import (
    IncomingPatientRecord,
)
from salesforce_to_canvas_integration.models.proxy import StaffProxy
from salesforce_to_canvas_integration.models.resolution_audit_entry import (
    ResolutionAuditEntry,
)
from salesforce_to_canvas_integration.services.canvas_fhir_client import (
    CanvasFhirAuthError,
    CanvasFhirError,
)
from salesforce_to_canvas_integration.services.patient_link import (
    SALESFORCE_IDENTIFIER_SYSTEM,
)


_DELETE_RECEIVED_AT = datetime(2026, 5, 28, 14, 30, tzinfo=timezone.utc)
_STAFF_KEY = "deadbeefdeadbeefdeadbeefdeadbeef"


class StaffProxyFactory(StaffFactory, factory.django.DjangoModelFactory[StaffProxy]):
    class Meta:
        model = StaffProxy


class DeleteRowFactory(factory.django.DjangoModelFactory[IncomingPatientRecord]):
    """A captured delete row pinned to a known external id and timestamp."""

    class Meta:
        model = IncomingPatientRecord

    external_id = "00QUNL01"
    source_object = "Contact"
    action = "delete"
    first_name = ""
    last_name = ""
    email = ""
    phone = ""
    raw_payload = factory.LazyFunction(lambda: {"Id": "00QUNL01"})
    content_hash = "hash-unlink-only-01"
    status = "new"
    received_at = _DELETE_RECEIVED_AT


class FakeFhirClient:
    """Records calls to remove_salesforce_identifier and scripts failures."""

    def __init__(self, *, raise_exc: Exception | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self._raise = raise_exc

    def remove_salesforce_identifier(
        self, patient_id: str, sf_external_id: str
    ) -> None:
        self.calls.append((patient_id, sf_external_id))
        if self._raise is not None:
            raise self._raise


def _fully_configured_secrets() -> dict[str, str]:
    return {
        "SF_WEBHOOK_SECRET": "whsec",
        "SF_CLIENT_ID": "cid",
        "SF_CLIENT_SECRET": "csec",
        "SF_LOGIN_URL": "https://login.salesforce.com",
        "SF_ADMIN_STAFF_IDS": _STAFF_KEY,
        "CANVAS_API_CLIENT_ID": "canvas-cid",
        "CANVAS_API_CLIENT_SECRET": "canvas-csec",
        "FUMAGE_BASE_URL": "https://fumage-example.canvasmedical.com",
    }


def _make_api(
    *,
    secrets: dict[str, str] | None = None,
    fhir_client: FakeFhirClient | None = None,
) -> SalesforceStatusAPI:
    handler = SalesforceStatusAPI.__new__(SalesforceStatusAPI)
    handler.event = MagicMock()
    handler.secrets = secrets if secrets is not None else _fully_configured_secrets()
    handler.environment = {}
    handler._handler = None
    handler._path_pattern = None
    if fhir_client is not None:
        handler._build_canvas_fhir_client = (  # type: ignore[method-assign]
            lambda config, _client=fhir_client: _client
        )
    return handler


def _request(
    *,
    external_id: str,
    staff_key: str | None = _STAFF_KEY,
) -> MagicMock:
    request = MagicMock()
    request.path_params = {"external_id": external_id}
    headers: dict[str, str] = {}
    if staff_key:
        headers["canvas-logged-in-user-id"] = staff_key
    request.headers.get.side_effect = headers.get
    return request


def _drive(api: SalesforceStatusAPI, request: MagicMock) -> list[Any]:
    type(api).request = PropertyMock(return_value=request)
    return api.unlink_only()


def _status(effect: Any) -> int:
    return int(json.loads(effect.payload)["status_code"])


def _json_body(effect: Any) -> dict[str, Any]:
    from base64 import b64decode

    payload = json.loads(effect.payload)
    return json.loads(b64decode(payload["body"]).decode())


def _seed_linked_patient(external_id: str) -> Any:
    patient = PatientFactory.create()
    today = date.today()
    PatientExternalIdentifier.objects.create(
        patient=patient,
        use="official",
        identifier_type="external",
        system=SALESFORCE_IDENTIFIER_SYSTEM,
        value=external_id,
        issued_date=today,
        expiration_date=today + timedelta(days=365),
    )
    return patient


def test_unlink_only_happy_path_flips_row_and_calls_fhir() -> None:
    patient = _seed_linked_patient("00QUNL01")
    DeleteRowFactory.create()
    staff = StaffProxyFactory.create(id=_STAFF_KEY)
    fhir = FakeFhirClient()

    responses = _drive(
        _make_api(fhir_client=fhir),
        _request(external_id="00QUNL01"),
    )

    row = IncomingPatientRecord.objects.get(external_id="00QUNL01")
    assert row.status == "accepted"
    assert row.actioned_at is not None
    assert row.actioned_by_id == staff.dbid
    assert fhir.calls == [(str(patient.id), "00QUNL01")]

    entry = ResolutionAuditEntry.objects.get(external_id="00QUNL01")
    assert entry.action_taken == "unlink"
    assert entry.result_patient_id == str(patient.id)

    assert _status(responses[0]) == HTTPStatus.OK
    body = _json_body(responses[0])
    assert body == {
        "status": "accepted",
        "external_id": "00QUNL01",
        "canvas_patient_id": str(patient.id),
    }
    # Unlink only talks to the Canvas FHIR API directly, no SDK effect is
    # returned alongside the JSON response.
    assert len(responses) == 1


def test_unlink_only_409s_when_no_linked_canvas_patient() -> None:
    DeleteRowFactory.create()
    fhir = FakeFhirClient()

    responses = _drive(
        _make_api(fhir_client=fhir),
        _request(external_id="00QUNL01"),
    )

    assert _status(responses[0]) == HTTPStatus.CONFLICT
    assert fhir.calls == []
    row = IncomingPatientRecord.objects.get(external_id="00QUNL01")
    assert row.status == "new"


def test_unlink_only_404s_when_no_delete_row_for_external_id() -> None:
    responses = _drive(
        _make_api(fhir_client=FakeFhirClient()),
        _request(external_id="00QMISSING"),
    )
    assert _status(responses[0]) == HTTPStatus.NOT_FOUND


def test_unlink_only_409s_when_row_already_acted() -> None:
    _seed_linked_patient("00QUNL01")
    DeleteRowFactory.create(status="accepted")
    fhir = FakeFhirClient()

    responses = _drive(
        _make_api(fhir_client=fhir),
        _request(external_id="00QUNL01"),
    )

    assert _status(responses[0]) == HTTPStatus.CONFLICT
    assert fhir.calls == []


@pytest.mark.parametrize(
    "missing_key",
    ["CANVAS_API_CLIENT_ID", "CANVAS_API_CLIENT_SECRET", "FUMAGE_BASE_URL"],
)
def test_unlink_only_503s_when_canvas_fhir_secret_missing(missing_key: str) -> None:
    _seed_linked_patient("00QUNL01")
    DeleteRowFactory.create()
    secrets = _fully_configured_secrets()
    secrets[missing_key] = ""
    fhir = FakeFhirClient()

    responses = _drive(
        _make_api(secrets=secrets, fhir_client=fhir),
        _request(external_id="00QUNL01"),
    )

    assert _status(responses[0]) == HTTPStatus.SERVICE_UNAVAILABLE
    body = _json_body(responses[0])
    assert "CANVAS_API_CLIENT_ID" in body["error"]
    assert "CANVAS_API_CLIENT_SECRET" in body["error"]
    assert "FUMAGE_BASE_URL" in body["error"]
    assert fhir.calls == []
    row = IncomingPatientRecord.objects.get(external_id="00QUNL01")
    assert row.status == "new"


def test_unlink_only_502s_with_underlying_message_on_fhir_failure() -> None:
    _seed_linked_patient("00QUNL01")
    DeleteRowFactory.create()
    fhir = FakeFhirClient(
        raise_exc=CanvasFhirError("Canvas FHIR PUT Patient failed (422): missing field")
    )

    responses = _drive(
        _make_api(fhir_client=fhir),
        _request(external_id="00QUNL01"),
    )

    assert _status(responses[0]) == HTTPStatus.BAD_GATEWAY
    body = _json_body(responses[0])
    assert "422" in body["error"]
    assert "missing field" in body["error"]
    row = IncomingPatientRecord.objects.get(external_id="00QUNL01")
    # Row stays at new on any failure path so the operator can retry.
    assert row.status == "new"


def test_unlink_only_502s_on_canvas_fhir_auth_error() -> None:
    _seed_linked_patient("00QUNL01")
    DeleteRowFactory.create()
    fhir = FakeFhirClient(
        raise_exc=CanvasFhirAuthError("token endpoint returned 401")
    )

    responses = _drive(
        _make_api(fhir_client=fhir),
        _request(external_id="00QUNL01"),
    )

    assert _status(responses[0]) == HTTPStatus.BAD_GATEWAY
    body = _json_body(responses[0])
    assert "401" in body["error"]
    row = IncomingPatientRecord.objects.get(external_id="00QUNL01")
    assert row.status == "new"
