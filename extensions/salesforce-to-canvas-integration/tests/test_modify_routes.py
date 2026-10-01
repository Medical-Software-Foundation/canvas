"""Tests for the modify audit routes on SalesforceStatusAPI.

Covers ``/records/<external_id>/apply-update`` (direct delta apply from the
captured payload) and ``/records/<external_id>/review-and-update`` (delta apply
from a reviewer edited form). The shared ``_apply_modify_update`` helper handles
the unlinked patient guard, so the 409 case is exercised against either entry
point.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
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
from salesforce_to_canvas_integration.services.patient_link import (
    SALESFORCE_IDENTIFIER_SYSTEM,
)

_MODIFY_PAYLOAD = {
    "Id": "00QMOD01",
    "FirstName": "Ada",
    "LastName": "King",
    "Email": "ada.king@example.com",
}


class StaffProxyFactory(StaffFactory, factory.django.DjangoModelFactory[StaffProxy]):
    class Meta:
        model = StaffProxy


class ModifyRowFactory(factory.django.DjangoModelFactory[IncomingPatientRecord]):
    """A captured modify row pinned to a known external id."""

    class Meta:
        model = IncomingPatientRecord

    external_id = "00QMOD01"
    source_object = "Contact"
    action = "modify"
    first_name = "Ada"
    last_name = "Lovelace"
    email = "ada@example.com"
    phone = ""
    raw_payload = factory.LazyFunction(lambda: dict(_MODIFY_PAYLOAD))
    content_hash = "hash-modify-01"
    status = "new"


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
    body: dict[str, Any] | None = None,
    staff_key: str | None = "deadbeefdeadbeefdeadbeefdeadbeef",
    body_raises: Exception | None = None,
    body_is_list: bool = False,
) -> MagicMock:
    request = MagicMock()
    request.path_params = {"external_id": external_id}
    headers: dict[str, str] = {}
    if staff_key:
        headers["canvas-logged-in-user-id"] = staff_key
    request.headers.get.side_effect = headers.get
    if body_raises is not None:
        request.json.side_effect = body_raises
    elif body_is_list:
        request.json.return_value = []
    else:
        request.json.return_value = body or {}
    return request


def _drive_apply_update(api: SalesforceStatusAPI, request: MagicMock) -> list[Any]:
    type(api).request = PropertyMock(return_value=request)
    return api.apply_update()


def _drive_review(api: SalesforceStatusAPI, request: MagicMock) -> list[Any]:
    type(api).request = PropertyMock(return_value=request)
    return api.review_and_update()


def _status(effect: Any) -> int:
    return int(json.loads(effect.payload)["status_code"])


def _json_body(effect: Any) -> dict[str, Any]:
    from base64 import b64decode

    payload = json.loads(effect.payload)
    return json.loads(b64decode(payload["body"]).decode())


def _seed_linked_patient(external_id: str) -> Any:
    """Create a Patient plus a PatientExternalIdentifier matching external_id."""
    patient = PatientFactory.create()
    # PatientExternalIdentifier carries non null DateFields, so seed minimal
    # values that satisfy the schema without driving any business logic.
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


# ---------------------------------------------------------------------------
# apply-update
# ---------------------------------------------------------------------------


def test_apply_update_route_marks_row_accepted_and_returns_effect() -> None:
    patient = _seed_linked_patient("00QMOD01")
    ModifyRowFactory.create()
    staff = StaffProxyFactory.create(id="deadbeefdeadbeefdeadbeefdeadbeef")

    responses = _drive_apply_update(_make_api(), _request(external_id="00QMOD01"))

    row = IncomingPatientRecord.objects.get(external_id="00QMOD01")
    assert row.status == "accepted"
    assert row.actioned_at is not None
    assert row.actioned_by_id == staff.dbid

    entry = ResolutionAuditEntry.objects.get(external_id="00QMOD01")
    assert entry.action == "modify"
    assert entry.action_taken == "modify_applied"
    assert entry.event_id == row.pk
    assert entry.result_patient_id == str(patient.id)

    assert _status(responses[0]) == HTTPStatus.OK
    body = _json_body(responses[0])
    assert body == {
        "status": "accepted",
        "external_id": "00QMOD01",
        "canvas_patient_id": str(patient.id),
    }
    update_effect = responses[1]
    rendered = repr(update_effect)
    # The update carries the captured first name and the patient target.
    assert "Ada" in rendered
    assert str(patient.id) in rendered


def test_apply_update_stores_the_canvas_before_snapshot() -> None:
    """The modify apply records the chart as it stood before the write.

    The Activity Details table later shows what was in Canvas against what the
    apply wrote, so the snapshot must reflect the linked patient, not the
    incoming modify values. See journal cnv-928/037.
    """
    patient = _seed_linked_patient("00QMOD01")
    ModifyRowFactory.create()
    StaffProxyFactory.create(id="deadbeefdeadbeefdeadbeefdeadbeef")

    _drive_apply_update(_make_api(), _request(external_id="00QMOD01"))

    entry = ResolutionAuditEntry.objects.get(external_id="00QMOD01")
    # The snapshot is the chart before the apply, the linked patient, distinct
    # from the incoming Ada King the modify payload carries.
    assert entry.canvas_before
    assert entry.canvas_before["first_name"] == patient.first_name
    assert entry.canvas_before["last_name"] == patient.last_name


def test_apply_update_route_409s_when_no_linked_canvas_patient() -> None:
    ModifyRowFactory.create()

    responses = _drive_apply_update(_make_api(), _request(external_id="00QMOD01"))

    assert _status(responses[0]) == HTTPStatus.CONFLICT
    # Row remains pending so the operator can run the create flow first.
    row = IncomingPatientRecord.objects.get(external_id="00QMOD01")
    assert row.status == "new"
    # The conflict short circuits before resolution, so nothing is logged.
    assert not ResolutionAuditEntry.objects.filter(external_id="00QMOD01").exists()


def test_apply_update_route_returns_404_when_external_id_is_unknown() -> None:
    responses = _drive_apply_update(_make_api(), _request(external_id="00QMISSING"))
    assert _status(responses[0]) == HTTPStatus.NOT_FOUND


def test_apply_update_route_returns_409_when_row_is_already_acted() -> None:
    _seed_linked_patient("00QMOD01")
    ModifyRowFactory.create(status="accepted")

    responses = _drive_apply_update(_make_api(), _request(external_id="00QMOD01"))

    assert _status(responses[0]) == HTTPStatus.CONFLICT


def test_apply_update_route_applies_a_previously_skipped_modify() -> None:
    """Story two, a skipped modify can be amended and applied directly."""
    patient = _seed_linked_patient("00QMOD01")
    ModifyRowFactory.create(status="dismissed")
    StaffProxyFactory.create(id="deadbeefdeadbeefdeadbeefdeadbeef")

    responses = _drive_apply_update(_make_api(), _request(external_id="00QMOD01"))

    row = IncomingPatientRecord.objects.get(external_id="00QMOD01")
    assert row.status == "accepted"

    entry = ResolutionAuditEntry.objects.get(
        external_id="00QMOD01", action_taken="modify_applied"
    )
    assert entry.result_patient_id == str(patient.id)

    assert _status(responses[0]) == HTTPStatus.OK


# ---------------------------------------------------------------------------
# review-and-update
# ---------------------------------------------------------------------------


def test_review_and_update_route_delta_applies_form_fields_only() -> None:
    patient = _seed_linked_patient("00QMOD01")
    ModifyRowFactory.create()
    StaffProxyFactory.create(id="deadbeefdeadbeefdeadbeefdeadbeef")

    body = {
        "first_name": "",
        "last_name": "",
        "email": "edited@example.com",
        "phone": "",
        "date_of_birth": "",
        "sex_at_birth": "",
        "telecom_mobile": "",
        "address_line_1": "",
        "address_line_2": "",
        "city": "",
        "state": "",
        "postal_code": "",
        "country": "",
    }
    responses = _drive_review(_make_api(), _request(external_id="00QMOD01", body=body))

    row = IncomingPatientRecord.objects.get(external_id="00QMOD01")
    assert row.status == "accepted"
    # Only email was edited, the typed columns reflect that.
    assert row.email == "edited@example.com"
    # The other typed columns keep their captured values because the form
    # supplied blanks and the delta apply contract leaves absent or empty
    # fields alone.
    assert row.last_name == "Lovelace"

    entry = ResolutionAuditEntry.objects.get(external_id="00QMOD01")
    assert entry.action_taken == "modify_applied"
    assert entry.result_patient_id == str(patient.id)

    assert _status(responses[0]) == HTTPStatus.OK
    update_effect = responses[1]
    rendered = repr(update_effect)
    assert "edited@example.com" in rendered
    assert str(patient.id) in rendered


def test_review_and_update_route_returns_404_when_external_id_is_unknown() -> None:
    responses = _drive_review(
        _make_api(),
        _request(external_id="00QMISSING", body={"email": "x@example.com"}),
    )
    assert _status(responses[0]) == HTTPStatus.NOT_FOUND


def test_review_and_update_route_returns_400_when_body_is_not_an_object() -> None:
    _seed_linked_patient("00QMOD01")
    ModifyRowFactory.create()

    responses = _drive_review(
        _make_api(),
        _request(external_id="00QMOD01", body=None, body_is_list=True),
    )
    assert _status(responses[0]) == HTTPStatus.BAD_REQUEST


def test_review_and_update_route_409s_when_no_linked_canvas_patient() -> None:
    ModifyRowFactory.create()

    responses = _drive_review(
        _make_api(),
        _request(external_id="00QMOD01", body={"email": "x@example.com"}),
    )
    assert _status(responses[0]) == HTTPStatus.CONFLICT
