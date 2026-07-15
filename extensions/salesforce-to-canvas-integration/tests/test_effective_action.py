"""Tests for the effective action derivation. See journal cnv-938/015 016.

A row's stored action is its arrival label, written once when the sync lands.
What the row means now is derived from the live patient link, so a create whose
Salesforce id has since been linked reads and routes as a modify of that
patient. These cover the pure derivation, the record view serialization, and
the route guards that make the create path unreachable once a patient exists.
"""

from __future__ import annotations

import json
from base64 import b64decode
from datetime import date, timedelta
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock, PropertyMock

import factory

from canvas_sdk.test_utils.factories import PatientFactory, StaffFactory
from canvas_sdk.v1.data.patient import PatientExternalIdentifier

from salesforce_to_canvas_integration.handlers.status_api import (
    SalesforceStatusAPI,
    _effective_action,
    _record_view,
)
from salesforce_to_canvas_integration.models.incoming_patient_record import (
    IncomingPatientRecord,
)
from salesforce_to_canvas_integration.models.proxy import StaffProxy
from salesforce_to_canvas_integration.models.resolution_audit_entry import (
    ResolutionAuditEntry,
)
from salesforce_to_canvas_integration.services.config import DEFAULT_FIELD_MAPPING
from salesforce_to_canvas_integration.services.patient_link import (
    SALESFORCE_IDENTIFIER_SYSTEM,
)

_EXTERNAL_ID = "003EFFECT01"

_CREATE_PAYLOAD = {
    "Id": _EXTERNAL_ID,
    "FirstName": "Tobias",
    "LastName": "Marquardt",
    "Email": "tobias@example.com",
    "Phone": "5550100",
    "Birthdate": "1987-03-14",
}


class CreateRowFactory(factory.django.DjangoModelFactory[IncomingPatientRecord]):
    """A captured create row pinned to a known external id."""

    class Meta:
        model = IncomingPatientRecord

    external_id = _EXTERNAL_ID
    source_object = "Contact"
    action = "create"
    first_name = "Tobias"
    last_name = "Marquardt"
    email = "tobias@example.com"
    phone = "5550100"
    raw_payload = factory.LazyFunction(lambda: dict(_CREATE_PAYLOAD))
    content_hash = factory.Sequence(lambda n: f"hash-effect-{n}")
    status = "new"


class StaffProxyFactory(StaffFactory, factory.django.DjangoModelFactory[StaffProxy]):
    class Meta:
        model = StaffProxy


def _seed_linked_patient(external_id: str) -> Any:
    """Create a Patient plus a PatientExternalIdentifier matching external_id."""
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
    event_id: int | None = None,
    body: dict[str, Any] | None = None,
    staff_key: str | None = "deadbeefdeadbeefdeadbeefdeadbeef",
) -> MagicMock:
    request = MagicMock()
    request.path_params = {"external_id": external_id}
    query: dict[str, str] = {}
    if event_id is not None:
        query["event_id"] = str(event_id)
    request.query_params = query
    headers: dict[str, str] = {}
    if staff_key:
        headers["canvas-logged-in-user-id"] = staff_key
    request.headers.get.side_effect = headers.get
    request.json.return_value = body or {}
    return request


def _status(effect: Any) -> int:
    return int(json.loads(effect.payload)["status_code"])


def _json_body(effect: Any) -> dict[str, Any]:
    payload = json.loads(effect.payload)
    return json.loads(b64decode(payload["body"]).decode())


# ---------------------------------------------------------------------------
# pure derivation
# ---------------------------------------------------------------------------


def test_effective_action_create_linked_reads_as_modify() -> None:
    assert _effective_action("create", True) == "modify"


def test_effective_action_create_unlinked_stays_create() -> None:
    assert _effective_action("create", False) == "create"


def test_effective_action_modify_passes_through_either_way() -> None:
    assert _effective_action("modify", True) == "modify"
    assert _effective_action("modify", False) == "modify"


def test_effective_action_delete_passes_through_either_way() -> None:
    assert _effective_action("delete", True) == "delete"
    assert _effective_action("delete", False) == "delete"


# ---------------------------------------------------------------------------
# record view
# ---------------------------------------------------------------------------


def test_record_view_linked_create_reads_as_modify() -> None:
    """A create row whose id is linked serializes as a modify, link preserved."""
    _seed_linked_patient(_EXTERNAL_ID)
    row = CreateRowFactory.create()

    view = _record_view(row, DEFAULT_FIELD_MAPPING)

    assert view["action"] == "modify"
    assert view["arrival_action"] == "create"
    assert view["linked"] is True


def test_record_view_unlinked_create_stays_create() -> None:
    """With no patient linked the create row keeps its create label."""
    row = CreateRowFactory.create()

    view = _record_view(row, DEFAULT_FIELD_MAPPING)

    assert view["action"] == "create"
    assert view["arrival_action"] == "create"
    assert view["linked"] is False


def test_record_view_trusts_a_precomputed_linked_flag() -> None:
    """The bucketing path passes its memoized lookup, the view trusts it."""
    row = CreateRowFactory.create()

    view = _record_view(row, DEFAULT_FIELD_MAPPING, linked=True)

    assert view["action"] == "modify"
    assert view["arrival_action"] == "create"


# ---------------------------------------------------------------------------
# route guards
# ---------------------------------------------------------------------------


def test_apply_update_accepts_a_linked_create_row() -> None:
    """Apply update resolves a stored create row through the modify path.

    This is the exact defect, a create labeled row arrived before the patient
    was approved, the patient now exists, and applying the row must update that
    patient rather than open a create flow.
    """
    patient = _seed_linked_patient(_EXTERNAL_ID)
    row = CreateRowFactory.create()
    StaffProxyFactory.create(id="deadbeefdeadbeefdeadbeefdeadbeef")

    api = _make_api()
    type(api).request = PropertyMock(
        return_value=_request(external_id=_EXTERNAL_ID, event_id=row.pk)
    )
    responses = api.apply_update()

    refreshed = IncomingPatientRecord.objects.get(pk=row.pk)
    assert refreshed.status == "accepted"

    entry = ResolutionAuditEntry.objects.get(event_id=row.pk)
    assert entry.action_taken == "modify_applied"

    assert _status(responses[0]) == HTTPStatus.OK
    body = _json_body(responses[0])
    assert body["canvas_patient_id"] == str(patient.id)


def test_accept_route_refuses_a_linked_record() -> None:
    """Create is unreachable once a patient is linked, the route returns 409."""
    _seed_linked_patient(_EXTERNAL_ID)
    row = CreateRowFactory.create()

    api = _make_api()
    type(api).request = PropertyMock(
        return_value=_request(
            external_id=_EXTERNAL_ID,
            event_id=row.pk,
            body={"last_name": "Marquardt"},
        )
    )
    responses = api.accept_record()

    assert _status(responses[0]) == HTTPStatus.CONFLICT
    assert "already exists" in _json_body(responses[0])["error"].lower()

    refreshed = IncomingPatientRecord.objects.get(pk=row.pk)
    assert refreshed.status == "new"


def test_accept_route_still_creates_an_unlinked_record() -> None:
    """An unlinked create row flows through accept unchanged."""
    row = CreateRowFactory.create()
    StaffProxyFactory.create(id="deadbeefdeadbeefdeadbeefdeadbeef")

    api = _make_api()
    type(api).request = PropertyMock(
        return_value=_request(
            external_id=_EXTERNAL_ID,
            event_id=row.pk,
            body={"first_name": "Tobias", "last_name": "Marquardt"},
        )
    )
    responses = api.accept_record()

    assert _status(responses[0]) == HTTPStatus.OK
    refreshed = IncomingPatientRecord.objects.get(pk=row.pk)
    assert refreshed.status == "accepted"


def test_accept_refuses_a_superseded_create_and_takes_the_newest() -> None:
    """Only the newest pending create accepts, an older one is superseded.

    Four quick edits before approval stack creates for one contact. The newest
    carries the current Salesforce truth, so accepting an older create is refused
    with a conflict naming the newer change while the row stays pending, and the
    newest accepts. See journal cnv-938/017 018.
    """
    from datetime import datetime, timezone

    older = CreateRowFactory.create(content_hash="hash-older")
    newer = CreateRowFactory.create(content_hash="hash-newer")
    IncomingPatientRecord.objects.filter(pk=older.pk).update(
        received_at=datetime(2026, 1, 1, tzinfo=timezone.utc)
    )
    IncomingPatientRecord.objects.filter(pk=newer.pk).update(
        received_at=datetime(2026, 2, 1, tzinfo=timezone.utc)
    )
    StaffProxyFactory.create(id="deadbeefdeadbeefdeadbeefdeadbeef")

    api = _make_api()
    type(api).request = PropertyMock(
        return_value=_request(
            external_id=_EXTERNAL_ID,
            event_id=older.pk,
            body={"first_name": "Tobias", "last_name": "Marquardt"},
        )
    )
    refused = api.accept_record()
    assert _status(refused[0]) == HTTPStatus.CONFLICT
    assert "newer change" in _json_body(refused[0])["error"].lower()
    assert IncomingPatientRecord.objects.get(pk=older.pk).status == "new"

    api2 = _make_api()
    type(api2).request = PropertyMock(
        return_value=_request(
            external_id=_EXTERNAL_ID,
            event_id=newer.pk,
            body={"first_name": "Tobias", "last_name": "Marquardt"},
        )
    )
    ok = api2.accept_record()
    assert _status(ok[0]) == HTTPStatus.OK
    assert IncomingPatientRecord.objects.get(pk=newer.pk).status == "accepted"
