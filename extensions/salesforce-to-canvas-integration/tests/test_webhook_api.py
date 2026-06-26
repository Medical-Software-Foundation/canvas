"""Tests for the inbound Salesforce deliberate sync webhook.

One route, ``/webhooks/patient/sync``, receives a nested body carrying a top
level ``intent`` and a ``record`` object. The plugin derives the stored action
from the intent and the record's link state, a delete intent becomes a delete
action, a sync becomes modify when the Salesforce Id is already linked and create
when it is not. The webhook captures a verified event as one IncomingPatientRecord row and
is idempotent, an identical resend collapses while a real change appends.

These tests drive the route method against the real ORM, so they run where
canvas_sdk is importable. The handler returns applied effects, so the HTTP
status lives inside the effect payload rather than on the response object.
"""

from __future__ import annotations

import json
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock, PropertyMock, patch

from salesforce_to_canvas_integration.handlers.webhook_api import (
    SalesforceWebhookSync,
)
from salesforce_to_canvas_integration.models.incoming_patient_record import (
    IncomingPatientRecord,
)
from salesforce_to_canvas_integration.services.config import load_config
from salesforce_to_canvas_integration.services.hmac_verify import (
    SIGNATURE_HEADER,
    compute_signature,
)

WEBHOOK_SECRET = "whsec_test_value"

# Where find_linked_patient_id is looked up, so a patch lands on the name the
# handler actually calls.
_LINK_LOOKUP = (
    "salesforce_to_canvas_integration.handlers.webhook_base.find_linked_patient_id"
)


def _secrets() -> dict[str, str]:
    """A complete secrets dict so load_config inside the route succeeds."""
    return {
        "SF_WEBHOOK_SECRET": WEBHOOK_SECRET,
        "SF_CLIENT_ID": "client-id",
        "SF_CLIENT_SECRET": "client-secret",
        "SF_LOGIN_URL": "https://login.salesforce.com",
        "SF_ADMIN_STAFF_IDS": "abc123def456",
    }


def _make_api(secrets: dict[str, str]) -> SalesforceWebhookSync:
    """Instantiate the handler without calling __init__, matching the repo idiom."""
    handler = SalesforceWebhookSync.__new__(SalesforceWebhookSync)
    handler.event = MagicMock()
    handler.secrets = secrets
    handler.environment = {}
    handler._handler = None
    handler._path_pattern = None
    return handler


def _envelope(intent: str, record: dict[str, Any]) -> dict[str, Any]:
    """Build the nested sync body the emitter posts."""
    return {"intent": intent, "record": record}


def _request(
    payload: Any,
    *,
    secret: str = WEBHOOK_SECRET,
    signature: str | None = None,
    raw_body: bytes | None = None,
) -> MagicMock:
    """Build a mock request whose body matches the payload and is signed.

    Pass an explicit signature to forge a bad one. Pass ``raw_body`` to produce a
    body that does not match the payload, used for malformed JSON tests.
    """
    body = raw_body if raw_body is not None else json.dumps(payload).encode("utf-8")
    sig = signature if signature is not None else compute_signature(secret, body)
    request = MagicMock()
    request.body = body
    request.headers = {SIGNATURE_HEADER: sig}
    if raw_body is not None:
        request.json.side_effect = ValueError("malformed json")
    else:
        request.json.return_value = payload
    return request


def _drive(
    api: SalesforceWebhookSync,
    request: MagicMock,
    *,
    linked_patient_id: str | None = None,
) -> list[Any]:
    """Point the handler at a request and invoke the sync route.

    ``linked_patient_id`` controls what the link lookup returns so a sync intent
    resolves to modify when set and create when None.
    """
    type(api).request = PropertyMock(return_value=request)
    with patch(_LINK_LOOKUP, return_value=linked_patient_id):
        responses: list[Any] = api.sync_route()
    return responses


def _status(effect: Any) -> int:
    """Read the HTTP status out of an applied SimpleAPI response effect."""
    return int(json.loads(effect.payload)["status_code"])


# ---------------------------------------------------------------------------
# Action derivation. The body intent plus the link state resolve to the stored
# action label the admin console buckets on.
# ---------------------------------------------------------------------------


def test_sync_unlinked_record_captures_a_create_row() -> None:
    secrets = _secrets()
    payload = _envelope("sync", {"Id": "003NEW", "FirstName": "Jane", "LastName": "Doe"})

    responses = _drive(_make_api(secrets), _request(payload), linked_patient_id=None)

    assert IncomingPatientRecord.objects.filter(external_id="003NEW").count() == 1
    row = IncomingPatientRecord.objects.get(external_id="003NEW")
    assert row.action == "create"
    assert row.status == "new"
    assert row.canvas_patient_id is None
    assert _status(responses[0]) == HTTPStatus.ACCEPTED


def test_sync_linked_record_captures_a_modify_row() -> None:
    secrets = _secrets()
    payload = _envelope(
        "sync", {"Id": "003LINK", "FirstName": "Janet", "LastName": "Doe"}
    )

    responses = _drive(
        _make_api(secrets), _request(payload), linked_patient_id="patient-123"
    )

    row = IncomingPatientRecord.objects.get(external_id="003LINK")
    assert row.action == "modify"
    assert row.status == "new"
    assert _status(responses[0]) == HTTPStatus.ACCEPTED


def test_delete_intent_captures_a_delete_row() -> None:
    secrets = _secrets()
    payload = _envelope("delete", {"Id": "003GONE"})

    responses = _drive(
        _make_api(secrets), _request(payload), linked_patient_id="patient-123"
    )

    row = IncomingPatientRecord.objects.get(external_id="003GONE")
    assert row.action == "delete"
    assert row.status == "new"
    assert _status(responses[0]) == HTTPStatus.ACCEPTED


def test_delete_record_with_only_id_is_accepted() -> None:
    """Delete needs no demographics, just the SF record Id, and the row lands."""
    secrets = _secrets()
    payload = _envelope("delete", {"Id": "003DELONLY"})

    responses = _drive(_make_api(secrets), _request(payload))

    row = IncomingPatientRecord.objects.get(external_id="003DELONLY")
    assert row.action == "delete"
    assert row.first_name == ""
    assert row.last_name == ""
    assert row.email == ""
    assert row.phone == ""
    assert _status(responses[0]) == HTTPStatus.ACCEPTED


def test_derive_action_resolves_intent_and_link_state() -> None:
    api = _make_api(_secrets())

    with patch(_LINK_LOOKUP, return_value=None):
        assert api._derive_action("sync", "003A") == "create"
    with patch(_LINK_LOOKUP, return_value="patient-1"):
        assert api._derive_action("sync", "003A") == "modify"
    # Delete never consults the link lookup, it is always a delete.
    with patch(_LINK_LOOKUP, return_value="patient-1") as lookup:
        assert api._derive_action("delete", "003A") == "delete"
        lookup.assert_not_called()


# ---------------------------------------------------------------------------
# Idempotency. The dedup key is the record id plus the derived action, so an
# identical resend collapses and a real demographic change appends.
# ---------------------------------------------------------------------------


def test_identical_resend_does_not_duplicate() -> None:
    secrets = _secrets()
    payload = _envelope("sync", {"Id": "003DUP", "FirstName": "Jane", "LastName": "Doe"})

    _drive(_make_api(secrets), _request(payload))
    responses = _drive(_make_api(secrets), _request(payload))

    assert IncomingPatientRecord.objects.filter(external_id="003DUP").count() == 1
    # The duplicate is still ack'd, not rejected.
    assert _status(responses[0]) == HTTPStatus.ACCEPTED


def test_changed_record_appends_a_new_row() -> None:
    secrets = _secrets()
    first = _envelope("sync", {"Id": "003CHG", "FirstName": "Jane", "LastName": "Doe"})
    second = _envelope(
        "sync", {"Id": "003CHG", "FirstName": "Janet", "LastName": "Doe"}
    )

    _drive(_make_api(secrets), _request(first))
    _drive(_make_api(secrets), _request(second))

    assert IncomingPatientRecord.objects.filter(external_id="003CHG").count() == 2


def test_sync_then_delete_for_same_record_stay_independent_rows() -> None:
    """A sync followed by a delete for the same SF id lands as two distinct rows."""
    secrets = _secrets()
    sync = _envelope("sync", {"Id": "003INDEP", "FirstName": "Jane", "LastName": "Doe"})
    delete = _envelope("delete", {"Id": "003INDEP"})

    _drive(_make_api(secrets), _request(sync), linked_patient_id=None)
    _drive(_make_api(secrets), _request(delete), linked_patient_id="patient-9")

    rows = IncomingPatientRecord.objects.filter(external_id="003INDEP")
    assert rows.count() == 2
    actions = sorted(r.action for r in rows)
    assert actions == ["create", "delete"]


# ---------------------------------------------------------------------------
# Rejection paths. A bad signature, malformed JSON, or a body that does not
# match the nested contract is refused and writes nothing.
# ---------------------------------------------------------------------------


def test_invalid_signature_is_rejected_and_writes_nothing() -> None:
    secrets = _secrets()
    payload = _envelope("sync", {"Id": "003BAD", "FirstName": "Jane", "LastName": "Doe"})

    responses = _drive(
        _make_api(secrets), _request(payload, signature="sha256=deadbeef")
    )

    assert IncomingPatientRecord.objects.filter(external_id="003BAD").count() == 0
    assert _status(responses[0]) == HTTPStatus.UNAUTHORIZED


def test_missing_intent_is_rejected_and_writes_nothing() -> None:
    secrets = _secrets()
    payload = {"record": {"Id": "003NOINTENT", "FirstName": "Jane"}}

    responses = _drive(_make_api(secrets), _request(payload))

    assert IncomingPatientRecord.objects.count() == 0
    assert _status(responses[0]) == HTTPStatus.BAD_REQUEST


def test_unknown_intent_value_is_rejected() -> None:
    secrets = _secrets()
    payload = _envelope("archive", {"Id": "003BADINTENT", "FirstName": "Jane"})

    responses = _drive(_make_api(secrets), _request(payload))

    assert IncomingPatientRecord.objects.count() == 0
    assert _status(responses[0]) == HTTPStatus.BAD_REQUEST


def test_missing_record_object_is_rejected() -> None:
    secrets = _secrets()
    payload = {"intent": "sync"}

    responses = _drive(_make_api(secrets), _request(payload))

    assert IncomingPatientRecord.objects.count() == 0
    assert _status(responses[0]) == HTTPStatus.BAD_REQUEST


def test_missing_record_id_is_rejected_and_writes_nothing() -> None:
    secrets = _secrets()
    payload = _envelope("sync", {"FirstName": "Jane", "LastName": "Doe"})

    responses = _drive(_make_api(secrets), _request(payload))

    assert IncomingPatientRecord.objects.count() == 0
    assert _status(responses[0]) == HTTPStatus.BAD_REQUEST


# ---------------------------------------------------------------------------
# Base class helper coverage. Calling the inherited helpers via the leaf class
# is sufficient because routing is the only thing the leaf adds.
# ---------------------------------------------------------------------------


def test_verify_request_rejects_bad_signature() -> None:
    secrets = _secrets()
    api = _make_api(secrets)
    type(api).request = PropertyMock(
        return_value=_request(
            _envelope("sync", {"Id": "003V"}), signature="sha256=deadbeef"
        )
    )

    effect = api._verify_request()

    assert effect is not None
    assert _status(effect) == HTTPStatus.UNAUTHORIZED


def test_parse_payload_rejects_non_dict() -> None:
    secrets = _secrets()
    api = _make_api(secrets)
    # JSON arrays are valid JSON but the webhook contract requires an object.
    type(api).request = PropertyMock(return_value=_request(["not", "a", "dict"]))

    intent, record, error = api._parse_payload()

    assert intent is None
    assert record is None
    assert error is not None
    assert _status(error) == HTTPStatus.BAD_REQUEST


def test_parse_payload_returns_intent_and_record() -> None:
    secrets = _secrets()
    api = _make_api(secrets)
    body = _envelope("sync", {"Id": "003PARSE", "FirstName": "Jane"})
    type(api).request = PropertyMock(return_value=_request(body))

    intent, record, error = api._parse_payload()

    assert error is None
    assert intent == "sync"
    assert record == {"Id": "003PARSE", "FirstName": "Jane"}


def test_capture_dedups_identical_retry() -> None:
    secrets = _secrets()
    api = _make_api(secrets)
    config = load_config(secrets)
    record = {"Id": "003CAP", "FirstName": "Jane", "LastName": "Doe"}

    first_row, first_id = api._capture(
        record=record, sf_record_id="003CAP", action="create", config=config
    )
    second_row, second_id = api._capture(
        record=record, sf_record_id="003CAP", action="create", config=config
    )

    # The first capture writes a row, the identical retry dedups to None.
    assert first_row is not None
    assert second_row is None
    assert first_id == second_id
    assert IncomingPatientRecord.objects.filter(external_id="003CAP").count() == 1
