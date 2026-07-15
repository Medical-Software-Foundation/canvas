"""Tests for the tag-deleted audit route on SalesforceStatusAPI.

Covers ``/records/<external_id>/tag-deleted``. The Dismiss leg of the delete
resolutions reuses the generalised skip route, see tests/test_audit_routes.py.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock, PropertyMock

import factory

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
from salesforce_to_canvas_integration.services.effect_builder import (
    SALESFORCE_DELETED_AT_METADATA_KEY,
)
from salesforce_to_canvas_integration.services.patient_link import (
    SALESFORCE_IDENTIFIER_SYSTEM,
)

_DELETE_RECEIVED_AT = datetime(2026, 5, 28, 14, 30, tzinfo=timezone.utc)


class StaffProxyFactory(StaffFactory, factory.django.DjangoModelFactory[StaffProxy]):
    class Meta:
        model = StaffProxy


class DeleteRowFactory(factory.django.DjangoModelFactory[IncomingPatientRecord]):
    """A captured delete row pinned to a known external id and timestamp."""

    class Meta:
        model = IncomingPatientRecord

    external_id = "00QDEL01"
    source_object = "Contact"
    action = "delete"
    first_name = ""
    last_name = ""
    email = ""
    phone = ""
    raw_payload = factory.LazyFunction(lambda: {"Id": "00QDEL01"})
    content_hash = "hash-delete-01"
    status = "new"
    received_at = _DELETE_RECEIVED_AT


def _secrets() -> dict[str, str]:
    return {
        "SF_WEBHOOK_SECRET": "whsec",
        "SF_CLIENT_ID": "cid",
        "SF_CLIENT_SECRET": "csec",
        "SF_LOGIN_URL": "https://login.salesforce.com",
        "SF_ADMIN_STAFF_IDS": "deadbeefdeadbeefdeadbeefdeadbeef",
    }


def _make_api() -> SalesforceStatusAPI:
    handler = SalesforceStatusAPI.__new__(SalesforceStatusAPI)
    handler.event = MagicMock()
    handler.secrets = _secrets()
    handler.environment = {}
    handler._handler = None
    handler._path_pattern = None
    return handler


def _request(
    *,
    external_id: str,
    staff_key: str | None = "deadbeefdeadbeefdeadbeefdeadbeef",
) -> MagicMock:
    request = MagicMock()
    request.path_params = {"external_id": external_id}
    headers: dict[str, str] = {}
    if staff_key:
        headers["canvas-logged-in-user-id"] = staff_key
    request.headers.get.side_effect = headers.get
    return request


def _drive_tag_deleted(api: SalesforceStatusAPI, request: MagicMock) -> list[Any]:
    type(api).request = PropertyMock(return_value=request)
    return api.tag_deleted()


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


def test_tag_deleted_route_marks_row_accepted_and_returns_effect() -> None:
    patient = _seed_linked_patient("00QDEL01")
    DeleteRowFactory.create()
    staff = StaffProxyFactory.create(id="deadbeefdeadbeefdeadbeefdeadbeef")

    responses = _drive_tag_deleted(_make_api(), _request(external_id="00QDEL01"))

    row = IncomingPatientRecord.objects.get(external_id="00QDEL01")
    assert row.status == "accepted"
    assert row.actioned_at is not None
    assert row.actioned_by_id == staff.dbid

    entry = ResolutionAuditEntry.objects.get(external_id="00QDEL01")
    assert entry.action == "delete"
    assert entry.action_taken == "tag_deleted"
    assert entry.result_patient_id == str(patient.id)

    assert _status(responses[0]) == HTTPStatus.OK
    body = _json_body(responses[0])
    assert body == {
        "status": "accepted",
        "external_id": "00QDEL01",
        "canvas_patient_id": str(patient.id),
    }

    update_effect = responses[1]
    rendered = repr(update_effect)
    assert SALESFORCE_DELETED_AT_METADATA_KEY in rendered
    # The effect timestamp reflects when the Salesforce delete event arrived,
    # not when the operator reviewed it. The model uses auto_now_add so the
    # captured received_at is the wall clock at insert time.
    assert row.received_at.isoformat() in rendered
    assert str(patient.id) in rendered


def test_tag_deleted_route_409s_when_no_linked_canvas_patient() -> None:
    DeleteRowFactory.create()

    responses = _drive_tag_deleted(_make_api(), _request(external_id="00QDEL01"))

    assert _status(responses[0]) == HTTPStatus.CONFLICT
    row = IncomingPatientRecord.objects.get(external_id="00QDEL01")
    assert row.status == "new"


def test_tag_deleted_route_404s_when_no_delete_row_for_external_id() -> None:
    responses = _drive_tag_deleted(_make_api(), _request(external_id="00QMISSING"))
    assert _status(responses[0]) == HTTPStatus.NOT_FOUND


def test_tag_deleted_route_409s_when_row_already_acted() -> None:
    _seed_linked_patient("00QDEL01")
    DeleteRowFactory.create(status="accepted")

    responses = _drive_tag_deleted(_make_api(), _request(external_id="00QDEL01"))

    assert _status(responses[0]) == HTTPStatus.CONFLICT
