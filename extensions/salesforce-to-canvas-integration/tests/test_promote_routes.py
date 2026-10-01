"""Tests for the promote audit routes on SalesforceStatusAPI.

Story five. An unlinked modify, a modify for a record with no Canvas patient,
can be promoted into a create. ``GET /records/<external_id>/promote-prefill``
returns the gap filled create form values plus the warning context, and
``POST /records/<external_id>/promote`` creates the patient from the modify,
logs ``promoted_to_create``, and closes any still open create so a later accept
cannot spawn a duplicate. See journal cnv-909/088 and 092 story five.
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
from salesforce_to_canvas_integration.services.patient_link import (
    SALESFORCE_IDENTIFIER_SYSTEM,
)

_EXTERNAL_ID = "00QMOD01"
_STAFF_KEY = "deadbeefdeadbeefdeadbeefdeadbeef"

# The modify carries a fresh email and last name but left the address blank.
_MODIFY_PAYLOAD = {
    "Id": _EXTERNAL_ID,
    "FirstName": "Ada",
    "LastName": "King",
    "Email": "ada.king@new.example.com",
}

# The earlier create carried the address and the older email.
_CREATE_PAYLOAD = {
    "Id": _EXTERNAL_ID,
    "FirstName": "Ada",
    "LastName": "King",
    "Email": "ada@old.example.com",
    "MailingCity": "Springfield",
    "MailingState": "IL",
}


class StaffProxyFactory(StaffFactory, factory.django.DjangoModelFactory[StaffProxy]):
    class Meta:
        model = StaffProxy


class ModifyRowFactory(factory.django.DjangoModelFactory[IncomingPatientRecord]):
    class Meta:
        model = IncomingPatientRecord

    external_id = _EXTERNAL_ID
    source_object = "Contact"
    action = "modify"
    first_name = "Ada"
    last_name = "King"
    email = "ada.king@new.example.com"
    phone = ""
    raw_payload = factory.LazyFunction(lambda: dict(_MODIFY_PAYLOAD))
    content_hash = "hash-modify-01"
    status = "new"


class CreateRowFactory(factory.django.DjangoModelFactory[IncomingPatientRecord]):
    class Meta:
        model = IncomingPatientRecord

    external_id = _EXTERNAL_ID
    source_object = "Contact"
    action = "create"
    first_name = "Ada"
    last_name = "King"
    email = "ada@old.example.com"
    phone = ""
    raw_payload = factory.LazyFunction(lambda: dict(_CREATE_PAYLOAD))
    content_hash = "hash-create-01"
    status = "new"


def _seed_create_before_modify(
    modify: IncomingPatientRecord, *, status: str = "dismissed"
) -> IncomingPatientRecord:
    """Seed a create row stamped earlier than the modify, in the given status.

    ``received_at`` is ``auto_now_add`` so a plain create cannot set it, and the
    freshest prior lookup filters strictly earlier events. A direct update pins
    the create one minute before the modify so the ordering is deterministic
    regardless of insert timing.
    """
    create = CreateRowFactory.create(status=status)
    earlier = modify.received_at - timedelta(minutes=1)
    IncomingPatientRecord.objects.filter(pk=create.pk).update(received_at=earlier)
    return IncomingPatientRecord.objects.get(pk=create.pk)


def _secrets() -> dict[str, str]:
    return {
        "SF_WEBHOOK_SECRET": "whsec",
        "SF_CLIENT_ID": "cid",
        "SF_CLIENT_SECRET": "csec",
        "SF_LOGIN_URL": "https://login.salesforce.com",
        "SF_ADMIN_STAFF_IDS": _STAFF_KEY,
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
    staff_key: str | None = _STAFF_KEY,
    event_id: int | None = None,
    body_is_list: bool = False,
) -> MagicMock:
    request = MagicMock()
    request.path_params = {"external_id": external_id}
    headers: dict[str, str] = {}
    if staff_key:
        headers["canvas-logged-in-user-id"] = staff_key
    request.headers.get.side_effect = headers.get
    params: dict[str, str] = {}
    if event_id is not None:
        params["event_id"] = str(event_id)
    request.query_params.get.side_effect = params.get
    if body_is_list:
        request.json.return_value = []
    else:
        request.json.return_value = body or {}
    return request


def _drive_prefill(api: SalesforceStatusAPI, request: MagicMock) -> list[Any]:
    type(api).request = PropertyMock(return_value=request)
    return api.promote_prefill()


def _drive_promote(api: SalesforceStatusAPI, request: MagicMock) -> list[Any]:
    type(api).request = PropertyMock(return_value=request)
    return api.promote_record()


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


def _create_form_body() -> dict[str, Any]:
    """A complete create form body, mirroring what the promote modal posts."""
    return {
        "first_name": "Ada",
        "last_name": "King",
        "date_of_birth": "1815-12-10",
        "sex_at_birth": "female",
        "email": "ada.king@new.example.com",
        "phone": "",
        "telecom_mobile": "",
        "address_line_1": "",
        "address_line_2": "",
        "city": "Springfield",
        "state": "IL",
        "postal_code": "",
        "country": "",
    }


# ---------------------------------------------------------------------------
# promote-prefill
# ---------------------------------------------------------------------------


def test_promote_prefill_gap_fills_blanks_and_flags_skipped_create() -> None:
    modify = ModifyRowFactory.create()
    _seed_create_before_modify(modify, status="dismissed")

    responses = _drive_prefill(_make_api(), _request(external_id=_EXTERNAL_ID))

    assert _status(responses[0]) == HTTPStatus.OK
    body = _json_body(responses[0])
    # Incoming email wins, the blank address fields are filled from the create.
    assert body["mapped"]["email"] == "ada.king@new.example.com"
    assert body["mapped"]["city"] == "Springfield"
    assert body["mapped"]["state"] == "IL"
    assert "city" in body["gap_filled"]
    assert "state" in body["gap_filled"]
    # email differs between the modify and the create, so it is the diff.
    assert body["changed"] == ["email"]
    # The skipped create surfaces for the warning banner.
    assert body["create_to_close"]["exists"] is True
    assert body["create_to_close"]["status"] == "dismissed"


def test_promote_prefill_without_prior_event_reports_no_create() -> None:
    ModifyRowFactory.create()

    responses = _drive_prefill(_make_api(), _request(external_id=_EXTERNAL_ID))

    body = _json_body(responses[0])
    assert body["gap_filled"] == []
    assert body["create_to_close"] == {"exists": False}


def test_promote_prefill_returns_404_for_unknown_record() -> None:
    responses = _drive_prefill(_make_api(), _request(external_id="00QMISSING"))
    assert _status(responses[0]) == HTTPStatus.NOT_FOUND


# ---------------------------------------------------------------------------
# promote
# ---------------------------------------------------------------------------


def test_promote_creates_patient_and_closes_skipped_create() -> None:
    modify = ModifyRowFactory.create()
    create = _seed_create_before_modify(modify, status="dismissed")
    StaffProxyFactory.create(id=_STAFF_KEY)

    responses = _drive_promote(
        _make_api(),
        _request(external_id=_EXTERNAL_ID, body=_create_form_body()),
    )

    assert _status(responses[0]) == HTTPStatus.OK
    assert _json_body(responses[0]) == {
        "status": "accepted",
        "external_id": _EXTERNAL_ID,
    }
    # The create effect carries the form data and the preserved Salesforce id.
    create_effect = responses[1]
    rendered = repr(create_effect)
    assert "King" in rendered
    assert _EXTERNAL_ID in rendered

    # The modify row resolves as promoted_to_create.
    modify_row = IncomingPatientRecord.objects.get(pk=modify.pk)
    assert modify_row.status == "accepted"
    promote_entry = ResolutionAuditEntry.objects.get(
        event_id=modify.pk, action_taken="promoted_to_create"
    )
    assert promote_entry.action == "modify"
    # A promote creates the patient from scratch, so there is no prior chart to
    # snapshot. The before stays empty. See journal cnv-928/037.
    assert promote_entry.canvas_before == {}

    # The skipped create is closed so it can never spawn a duplicate, and the
    # closure is its own decision entry.
    create_row = IncomingPatientRecord.objects.get(pk=create.pk)
    assert create_row.status == "accepted"
    assert ResolutionAuditEntry.objects.filter(
        event_id=create.pk, action_taken="create_superseded"
    ).exists()


def test_promote_closes_a_still_open_create() -> None:
    modify = ModifyRowFactory.create()
    create = _seed_create_before_modify(modify, status="new")
    StaffProxyFactory.create(id=_STAFF_KEY)

    _drive_promote(
        _make_api(),
        _request(external_id=_EXTERNAL_ID, body=_create_form_body()),
    )

    create_row = IncomingPatientRecord.objects.get(pk=create.pk)
    assert create_row.status == "accepted"
    assert ResolutionAuditEntry.objects.filter(
        event_id=create.pk, action_taken="create_superseded"
    ).exists()


def test_promote_with_no_prior_create_creates_patient_and_closes_nothing() -> None:
    modify = ModifyRowFactory.create()
    StaffProxyFactory.create(id=_STAFF_KEY)

    responses = _drive_promote(
        _make_api(),
        _request(external_id=_EXTERNAL_ID, body=_create_form_body()),
    )

    assert _status(responses[0]) == HTTPStatus.OK
    modify_row = IncomingPatientRecord.objects.get(pk=modify.pk)
    assert modify_row.status == "accepted"
    # No create existed, so nothing was superseded.
    assert not ResolutionAuditEntry.objects.filter(
        action_taken="create_superseded"
    ).exists()


def test_promote_409s_when_a_canvas_patient_already_exists() -> None:
    modify = ModifyRowFactory.create()
    _seed_linked_patient(_EXTERNAL_ID)

    responses = _drive_promote(
        _make_api(),
        _request(external_id=_EXTERNAL_ID, body=_create_form_body()),
    )

    assert _status(responses[0]) == HTTPStatus.CONFLICT
    # The modify stays pending, promote was the wrong door, apply update is.
    modify_row = IncomingPatientRecord.objects.get(pk=modify.pk)
    assert modify_row.status == "new"
    assert not ResolutionAuditEntry.objects.filter(event_id=modify.pk).exists()


def test_promote_400s_when_last_name_is_missing() -> None:
    ModifyRowFactory.create()

    body = _create_form_body()
    body["last_name"] = ""
    responses = _drive_promote(
        _make_api(), _request(external_id=_EXTERNAL_ID, body=body)
    )

    assert _status(responses[0]) == HTTPStatus.BAD_REQUEST


def test_promote_returns_404_for_unknown_record() -> None:
    responses = _drive_promote(
        _make_api(),
        _request(external_id="00QMISSING", body=_create_form_body()),
    )
    assert _status(responses[0]) == HTTPStatus.NOT_FOUND


def test_promote_event_id_for_another_action_is_not_found() -> None:
    """A create event id handed to promote is rejected, promote targets modify."""
    modify = ModifyRowFactory.create()
    create = _seed_create_before_modify(modify, status="new")

    responses = _drive_promote(
        _make_api(),
        _request(
            external_id=_EXTERNAL_ID, body=_create_form_body(), event_id=create.pk
        ),
    )

    assert _status(responses[0]) == HTTPStatus.NOT_FOUND


def test_promote_refuses_a_superseded_modify_and_acts_on_the_newest() -> None:
    """Only the newest pending modify promotes, an older one is superseded.

    The newest arrival carries the current Salesforce truth, so promoting an
    older modify by its event id is refused with a conflict while the row stays
    pending, and the newest modify promotes cleanly. This replaces the old act
    on any clicked event behavior. See journal cnv-938/017 018.
    """
    older = ModifyRowFactory.create(content_hash="hash-modify-old")
    newer = ModifyRowFactory.create(content_hash="hash-modify-new")
    StaffProxyFactory.create(id=_STAFF_KEY)

    refused = _drive_promote(
        _make_api(),
        _request(
            external_id=_EXTERNAL_ID, body=_create_form_body(), event_id=older.pk
        ),
    )
    assert _status(refused[0]) == HTTPStatus.CONFLICT
    assert "newer change" in _json_body(refused[0])["error"].lower()
    assert IncomingPatientRecord.objects.get(pk=older.pk).status == "new"

    _drive_promote(
        _make_api(),
        _request(
            external_id=_EXTERNAL_ID, body=_create_form_body(), event_id=newer.pk
        ),
    )
    assert IncomingPatientRecord.objects.get(pk=newer.pk).status == "accepted"
