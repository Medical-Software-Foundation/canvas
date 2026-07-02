"""Tests for the audit accept and skip routes on SalesforceStatusAPI.

These drive the route methods directly against the ORM, the same idiom used by
``test_webhook_api`` and ``test_status_view``. The handler returns applied
SimpleAPI response effects, so the HTTP status lives inside the effect payload.
"""

from __future__ import annotations

import json
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock, PropertyMock

import factory

from canvas_sdk.test_utils.factories import StaffFactory

from salesforce_to_canvas_integration.handlers.status_api import SalesforceStatusAPI
from salesforce_to_canvas_integration.models.incoming_patient_record import (
    IncomingPatientRecord,
)
from salesforce_to_canvas_integration.models.proxy import StaffProxy
from salesforce_to_canvas_integration.models.resolution_audit_entry import (
    ResolutionAuditEntry,
)

_LEAD_PAYLOAD = {
    "Id": "00QAUDIT01",
    "FirstName": "Ada",
    "LastName": "Lovelace",
    "Email": "ada@example.com",
    "Phone": "+15551112222",
    "MobilePhone": "+15553334444",
    "Birthdate": "1990-04-15",
    "Gender": "female",
    "MailingStreet": "1 Analytical Way",
    "MailingCity": "London",
    "MailingState": "CA",
    "MailingPostalCode": "90210",
    "MailingCountry": "US",
}


class StaffProxyFactory(StaffFactory, factory.django.DjangoModelFactory[StaffProxy]):
    """StaffProxy factory for the actioned_by foreign key lookup."""

    class Meta:
        model = StaffProxy


class AuditRowFactory(factory.django.DjangoModelFactory[IncomingPatientRecord]):
    """A captured Lead row pinned to a known external id for the audit tests."""

    class Meta:
        model = IncomingPatientRecord

    external_id = "00QAUDIT01"
    source_object = "Lead"
    action = "create"
    first_name = "Ada"
    last_name = "Lovelace"
    email = "ada@example.com"
    phone = "+15551112222"
    raw_payload = factory.LazyFunction(lambda: dict(_LEAD_PAYLOAD))
    content_hash = "hash-audit-01"
    status = "new"


_FORM_BODY: dict[str, Any] = {
    "first_name": "Ada",
    "last_name": "King Lovelace",
    "date_of_birth": "1990-04-15",
    "sex_at_birth": "female",
    "email": "ada.king@example.com",
    "phone": "+15551112222",
    "telecom_mobile": "+15553334444",
    "address_line_1": "1 Analytical Way",
    "city": "London",
    "state": "CA",
    "postal_code": "90210",
    "country": "US",
}


def _secrets() -> dict[str, str]:
    """A complete secrets dict so load_config succeeds in the audit path."""
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
    body: dict[str, Any] | None,
    staff_key: str | None = "deadbeefdeadbeefdeadbeefdeadbeef",
    body_raises: Exception | None = None,
    body_is_list: bool = False,
    event_id: int | None = None,
) -> MagicMock:
    request = MagicMock()
    request.path_params = {"external_id": external_id}
    query: dict[str, str] = {}
    if event_id is not None:
        query["event_id"] = str(event_id)
    request.query_params.get.side_effect = query.get
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


def _drive_accept(api: SalesforceStatusAPI, request: MagicMock) -> list[Any]:
    type(api).request = PropertyMock(return_value=request)
    return api.accept_record()


def _drive_skip(api: SalesforceStatusAPI, request: MagicMock) -> list[Any]:
    type(api).request = PropertyMock(return_value=request)
    return api.skip_record()


def _drive_reopen(api: SalesforceStatusAPI, request: MagicMock) -> list[Any]:
    type(api).request = PropertyMock(return_value=request)
    return api.reopen_record()


def _status(effect: Any) -> int:
    return int(json.loads(effect.payload)["status_code"])


def _json_body(effect: Any) -> dict[str, Any]:
    from base64 import b64decode

    payload = json.loads(effect.payload)
    return json.loads(b64decode(payload["body"]).decode())


def test_accept_route_flips_row_and_emits_create_effect() -> None:
    AuditRowFactory.create()
    staff = StaffProxyFactory.create(
        id="deadbeefdeadbeefdeadbeefdeadbeef",
        first_name="Grace",
        last_name="Hopper",
    )

    responses = _drive_accept(
        _make_api(),
        _request(external_id="00QAUDIT01", body=_FORM_BODY),
    )

    row = IncomingPatientRecord.objects.get(external_id="00QAUDIT01")
    assert row.status == "accepted"
    assert row.actioned_at is not None
    assert row.actioned_by_id == staff.dbid
    # Edited last name survived the form path through MappedPatient and back.
    assert row.last_name == "King Lovelace"
    assert row.email == "ada.king@example.com"

    entry = ResolutionAuditEntry.objects.get(external_id="00QAUDIT01")
    assert entry.action == "create"
    assert entry.action_taken == "created"
    assert entry.event_id == row.pk
    assert entry.staff_key == "deadbeefdeadbeefdeadbeefdeadbeef"
    assert entry.staff_name == "Grace Hopper"

    assert _status(responses[0]) == HTTPStatus.OK
    assert _json_body(responses[0]) == {
        "status": "accepted",
        "external_id": "00QAUDIT01",
    }
    create_effect = responses[1]
    rendered = repr(create_effect)
    assert "King Lovelace" in rendered
    assert "salesforce" in rendered.lower()


def test_accept_route_returns_404_when_external_id_is_unknown() -> None:
    responses = _drive_accept(
        _make_api(),
        _request(external_id="00QMISSING", body=_FORM_BODY),
    )

    assert _status(responses[0]) == HTTPStatus.NOT_FOUND


def test_accept_route_returns_409_when_row_is_already_acted() -> None:
    AuditRowFactory.create(status="accepted")

    responses = _drive_accept(
        _make_api(),
        _request(external_id="00QAUDIT01", body=_FORM_BODY),
    )

    assert _status(responses[0]) == HTTPStatus.CONFLICT


def test_accept_route_returns_400_when_body_is_not_an_object() -> None:
    AuditRowFactory.create()

    responses = _drive_accept(
        _make_api(),
        _request(external_id="00QAUDIT01", body=None, body_is_list=True),
    )

    assert _status(responses[0]) == HTTPStatus.BAD_REQUEST


def test_accept_route_returns_400_when_body_is_invalid_json() -> None:
    AuditRowFactory.create()

    responses = _drive_accept(
        _make_api(),
        _request(
            external_id="00QAUDIT01",
            body=None,
            body_raises=ValueError("broken json"),
        ),
    )

    assert _status(responses[0]) == HTTPStatus.BAD_REQUEST


def test_accept_route_returns_400_when_last_name_is_missing() -> None:
    AuditRowFactory.create()
    body = dict(_FORM_BODY)
    body["last_name"] = ""

    responses = _drive_accept(
        _make_api(),
        _request(external_id="00QAUDIT01", body=body),
    )

    assert _status(responses[0]) == HTTPStatus.BAD_REQUEST


def test_accept_route_tolerates_missing_staff_lookup() -> None:
    """A session staff key that does not resolve to a StaffProxy still accepts."""
    AuditRowFactory.create()

    responses = _drive_accept(
        _make_api(),
        _request(external_id="00QAUDIT01", body=_FORM_BODY, staff_key="unknownkey00000000000000000000aa"),
    )

    row = IncomingPatientRecord.objects.get(external_id="00QAUDIT01")
    assert row.status == "accepted"
    assert row.actioned_by_id is None
    assert _status(responses[0]) == HTTPStatus.OK


def test_skip_route_flips_row_to_dismissed_and_emits_no_effect() -> None:
    AuditRowFactory.create()
    staff = StaffProxyFactory.create(id="deadbeefdeadbeefdeadbeefdeadbeef")

    responses = _drive_skip(
        _make_api(),
        _request(external_id="00QAUDIT01", body=None),
    )

    row = IncomingPatientRecord.objects.get(external_id="00QAUDIT01")
    assert row.status == "dismissed"
    assert row.actioned_at is not None
    assert row.actioned_by_id == staff.dbid
    assert row.canvas_patient_id is None

    entry = ResolutionAuditEntry.objects.get(external_id="00QAUDIT01")
    assert entry.action_taken == "skipped"
    assert entry.event_id == row.pk

    assert len(responses) == 1
    assert _status(responses[0]) == HTTPStatus.OK
    assert _json_body(responses[0]) == {
        "status": "skipped",
        "external_id": "00QAUDIT01",
    }


def test_skip_route_returns_404_when_external_id_is_unknown() -> None:
    responses = _drive_skip(
        _make_api(),
        _request(external_id="00QMISSING", body=None),
    )

    assert _status(responses[0]) == HTTPStatus.NOT_FOUND


def test_skip_route_returns_409_when_row_is_already_acted() -> None:
    AuditRowFactory.create(status="dismissed")

    responses = _drive_skip(
        _make_api(),
        _request(external_id="00QAUDIT01", body=None),
    )

    assert _status(responses[0]) == HTTPStatus.CONFLICT


def test_skip_route_dismisses_modify_row_when_newest() -> None:
    """Skip dispatches on the newest pending row regardless of action."""
    AuditRowFactory.create(action="modify")

    responses = _drive_skip(
        _make_api(),
        _request(external_id="00QAUDIT01", body=None),
    )

    row = IncomingPatientRecord.objects.get(external_id="00QAUDIT01")
    assert row.status == "dismissed"
    assert row.action == "modify"
    assert _status(responses[0]) == HTTPStatus.OK


def test_skip_route_stores_a_posted_note_on_the_ledger() -> None:
    """A posted skip note lands on the decision log entry, trimmed.

    See journal cnv-928/012.
    """
    AuditRowFactory.create()
    StaffProxyFactory.create(id="deadbeefdeadbeefdeadbeefdeadbeef")

    _drive_skip(
        _make_api(),
        _request(external_id="00QAUDIT01", body={"note": "  duplicate of an open lead  "}),
    )

    entry = ResolutionAuditEntry.objects.get(external_id="00QAUDIT01")
    assert entry.action_taken == "skipped"
    assert entry.note == "duplicate of an open lead"


def test_skip_route_stores_an_empty_note_when_none_posted() -> None:
    """A skip with no note posts an empty string, the existing default.

    See journal cnv-928/012.
    """
    AuditRowFactory.create()
    StaffProxyFactory.create(id="deadbeefdeadbeefdeadbeefdeadbeef")

    _drive_skip(
        _make_api(),
        _request(external_id="00QAUDIT01", body={}),
    )

    entry = ResolutionAuditEntry.objects.get(external_id="00QAUDIT01")
    assert entry.note == ""


def test_skip_route_tolerates_a_malformed_body() -> None:
    """A malformed body degrades to an empty note rather than failing the skip.

    The no body callers and tests keep working. See journal cnv-928/012.
    """
    AuditRowFactory.create()
    StaffProxyFactory.create(id="deadbeefdeadbeefdeadbeefdeadbeef")

    responses = _drive_skip(
        _make_api(),
        _request(external_id="00QAUDIT01", body=None, body_raises=ValueError("bad json")),
    )

    row = IncomingPatientRecord.objects.get(external_id="00QAUDIT01")
    assert row.status == "dismissed"
    assert _status(responses[0]) == HTTPStatus.OK
    entry = ResolutionAuditEntry.objects.get(external_id="00QAUDIT01")
    assert entry.note == ""


def test_skip_route_dismisses_delete_row_when_newest() -> None:
    """Dismiss on a delete row reuses the generalised skip dispatcher."""
    AuditRowFactory.create(action="delete")

    responses = _drive_skip(
        _make_api(),
        _request(external_id="00QAUDIT01", body=None),
    )

    row = IncomingPatientRecord.objects.get(external_id="00QAUDIT01")
    assert row.status == "dismissed"
    assert row.action == "delete"
    assert _status(responses[0]) == HTTPStatus.OK


# ---------------------------------------------------------------------------
# reopen, story two reversible skip
# ---------------------------------------------------------------------------


def test_reopen_route_returns_skipped_row_to_needs_action() -> None:
    """A dismissed row flips back to new and the reopen is logged."""
    AuditRowFactory.create(status="dismissed", action="modify")
    staff = StaffProxyFactory.create(
        id="deadbeefdeadbeefdeadbeefdeadbeef",
        first_name="Grace",
        last_name="Hopper",
    )

    responses = _drive_reopen(
        _make_api(),
        _request(external_id="00QAUDIT01", body=None),
    )

    row = IncomingPatientRecord.objects.get(external_id="00QAUDIT01")
    assert row.status == "new"
    # The row is pending again, so its resolution stamp is cleared.
    assert row.actioned_at is None
    assert row.actioned_by_id is None

    entry = ResolutionAuditEntry.objects.get(
        external_id="00QAUDIT01", action_taken="reopened"
    )
    assert entry.action == "modify"
    assert entry.event_id == row.pk
    # The reopener is still captured on the log even though the row stamp is clear.
    assert entry.staff_key == "deadbeefdeadbeefdeadbeefdeadbeef"
    assert entry.staff_name == "Grace Hopper"
    assert entry.staff_key == staff.id

    assert _status(responses[0]) == HTTPStatus.OK
    assert _json_body(responses[0]) == {
        "status": "reopened",
        "external_id": "00QAUDIT01",
    }


def test_reopen_route_returns_404_when_external_id_is_unknown() -> None:
    responses = _drive_reopen(
        _make_api(),
        _request(external_id="00QMISSING", body=None),
    )

    assert _status(responses[0]) == HTTPStatus.NOT_FOUND


def test_reopen_route_409s_when_row_is_not_skipped() -> None:
    """A pending row has nothing to reopen."""
    AuditRowFactory.create(status="new")

    responses = _drive_reopen(
        _make_api(),
        _request(external_id="00QAUDIT01", body=None),
    )

    assert _status(responses[0]) == HTTPStatus.CONFLICT
    # The row is left untouched and no decision entry is written.
    row = IncomingPatientRecord.objects.get(external_id="00QAUDIT01")
    assert row.status == "new"
    assert not ResolutionAuditEntry.objects.filter(external_id="00QAUDIT01").exists()


def test_reopen_route_409s_when_row_is_accepted() -> None:
    """An accepted row is not reopenable through this route."""
    AuditRowFactory.create(status="accepted")

    responses = _drive_reopen(
        _make_api(),
        _request(external_id="00QAUDIT01", body=None),
    )

    assert _status(responses[0]) == HTTPStatus.CONFLICT


def test_accept_route_accepts_a_previously_skipped_row() -> None:
    """Amend and accept directly from skipped, the reversible skip path."""
    AuditRowFactory.create(status="dismissed")
    StaffProxyFactory.create(id="deadbeefdeadbeefdeadbeefdeadbeef")

    responses = _drive_accept(
        _make_api(),
        _request(external_id="00QAUDIT01", body=_FORM_BODY),
    )

    row = IncomingPatientRecord.objects.get(external_id="00QAUDIT01")
    assert row.status == "accepted"

    entry = ResolutionAuditEntry.objects.get(
        external_id="00QAUDIT01", action_taken="created"
    )
    assert entry.event_id == row.pk

    assert _status(responses[0]) == HTTPStatus.OK
    # The create effect still fires on the amend and accept path.
    assert len(responses) == 2


# ---------------------------------------------------------------------------
# per event targeting, story four
# ---------------------------------------------------------------------------


def test_reopen_targets_a_specific_skipped_event_by_event_id() -> None:
    """A skipped create behind a newer pending modify is reopenable by event id.

    This is the per event queue headline. Without the event id the route falls
    back to the newest row, the pending modify, and refuses with a conflict.
    With the skipped create's event id it reopens that exact event and leaves
    the newer modify untouched. See journal cnv-909/092 story four.
    """
    from datetime import UTC, datetime

    create = AuditRowFactory.create(
        external_id="00QAUDIT01",
        action="create",
        status="dismissed",
        content_hash="hash-create",
    )
    modify = AuditRowFactory.create(
        external_id="00QAUDIT01",
        action="modify",
        status="new",
        content_hash="hash-modify",
    )
    IncomingPatientRecord.objects.filter(dbid=create.dbid).update(
        received_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    IncomingPatientRecord.objects.filter(dbid=modify.dbid).update(
        received_at=datetime(2026, 2, 1, tzinfo=UTC)
    )
    StaffProxyFactory.create(
        id="deadbeefdeadbeefdeadbeefdeadbeef",
        first_name="Grace",
        last_name="Hopper",
    )

    # The newest of record fallback hits the pending modify and refuses.
    fallback = _drive_reopen(
        _make_api(),
        _request(external_id="00QAUDIT01", body=None),
    )
    assert _status(fallback[0]) == HTTPStatus.CONFLICT

    # Targeting the skipped create by event id reopens that exact event.
    responses = _drive_reopen(
        _make_api(),
        _request(external_id="00QAUDIT01", body=None, event_id=create.pk),
    )
    assert _status(responses[0]) == HTTPStatus.OK
    create.refresh_from_db()
    modify.refresh_from_db()
    assert create.status == "new"
    assert modify.status == "new"
    entry = ResolutionAuditEntry.objects.get(
        external_id="00QAUDIT01", action_taken="reopened"
    )
    assert entry.event_id == create.pk


def test_reopen_rejects_an_event_id_from_another_record() -> None:
    """A crafted or stale event id pointing at another record is not found."""
    AuditRowFactory.create(external_id="00QAUDIT01", status="dismissed")
    other = AuditRowFactory.create(
        external_id="00QOTHER01",
        status="dismissed",
        content_hash="hash-other",
    )

    responses = _drive_reopen(
        _make_api(),
        _request(external_id="00QAUDIT01", body=None, event_id=other.pk),
    )

    assert _status(responses[0]) == HTTPStatus.NOT_FOUND


def test_accept_rejects_an_event_id_with_a_mismatched_action() -> None:
    """accept targets create events, a modify event id is treated as not found."""
    AuditRowFactory.create(external_id="00QAUDIT01", action="create", status="new")
    modify = AuditRowFactory.create(
        external_id="00QAUDIT01",
        action="modify",
        status="new",
        content_hash="hash-modify",
    )

    responses = _drive_accept(
        _make_api(),
        _request(external_id="00QAUDIT01", body=_FORM_BODY, event_id=modify.pk),
    )

    assert _status(responses[0]) == HTTPStatus.NOT_FOUND
