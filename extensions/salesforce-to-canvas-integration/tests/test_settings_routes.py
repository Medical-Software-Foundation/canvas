"""Tests for the sync automation settings routes on SalesforceStatusAPI.

Covers ``GET /settings`` and ``PUT /settings``. The routes drive the singleton
loader and writer directly against the ORM, the same idiom the other status API
route tests use, so the HTTP status lives inside the applied SimpleAPI response
effect. They also pin the admin gate on the class authenticate, the PUT shape
validation including the required field catalog membership, and that the GET
payload overlays the code defaults when no row exists. The held row reason thread into
``_record_view`` is checked alongside, since step five lit that read path. See
journal cnv-938/038.
"""

from __future__ import annotations

import json
from base64 import b64decode
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock, PropertyMock, patch

from canvas_sdk.handlers.simple_api import StaffSessionAuthMixin

from salesforce_to_canvas_integration.handlers.status_api import (
    SalesforceStatusAPI,
    _record_view,
)
from salesforce_to_canvas_integration.models.incoming_patient_record import (
    IncomingPatientRecord,
)
from salesforce_to_canvas_integration.models.sync_settings import (
    SINGLETON_KEY,
    SyncSettingsRecord,
    load_sync_settings,
)
from salesforce_to_canvas_integration.services.sync_rules import SyncSettings

_ADMIN_KEY = "4150cd20de8a470aa570a852859ac87e"
_OTHER_KEY = "6d3680b8bc224893ad7211bf1ecd33b3"


def _secrets() -> dict[str, str]:
    return {
        "SF_WEBHOOK_SECRET": "whsec",
        "SF_CLIENT_ID": "cid",
        "SF_CLIENT_SECRET": "csec",
        "SF_LOGIN_URL": "https://login.salesforce.com",
        "SF_ADMIN_STAFF_IDS": _ADMIN_KEY,
    }


def _make_api() -> SalesforceStatusAPI:
    handler = SalesforceStatusAPI.__new__(SalesforceStatusAPI)
    handler.event = MagicMock()
    handler.secrets = _secrets()
    handler.environment = {}
    handler._handler = None
    handler._path_pattern = None
    return handler


def _request(*, body: Any = None, body_raises: Exception | None = None) -> MagicMock:
    request = MagicMock()
    request.path_params = {}
    request.query_params.get.side_effect = {}.get
    request.headers.get.side_effect = {}.get
    if body_raises is not None:
        request.json.side_effect = body_raises
    else:
        request.json.return_value = body
    return request


def _drive_get(api: SalesforceStatusAPI, request: MagicMock) -> list[Any]:
    type(api).request = PropertyMock(return_value=request)
    result: list[Any] = api.get_settings()
    return result


def _drive_put(api: SalesforceStatusAPI, request: MagicMock) -> list[Any]:
    type(api).request = PropertyMock(return_value=request)
    result: list[Any] = api.put_settings()
    return result


def _status(effect: Any) -> int:
    return int(json.loads(effect.payload)["status_code"])


def _json_body(effect: Any) -> dict[str, Any]:
    payload = json.loads(effect.payload)
    body: dict[str, Any] = json.loads(b64decode(payload["body"]).decode())
    return body


def _valid_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "auto_create": True,
        "auto_modify": False,
        "auto_delete": True,
        "delete_action": "tag_deleted",
        "required_fields": ["first_name", "last_name", "email"],
        "address_group_integrity": False,
        "validity_checks": True,
    }
    body.update(overrides)
    return body


# ---- GET, the defaults overlay and a persisted row ----------------------


def test_get_returns_code_defaults_when_no_row() -> None:
    responses = _drive_get(_make_api(), _request())

    assert _status(responses[0]) == HTTPStatus.OK
    body = _json_body(responses[0])
    defaults = SyncSettings()
    assert body["settings"] == {
        "auto_create": defaults.auto_create,
        "auto_modify": defaults.auto_modify,
        "auto_delete": defaults.auto_delete,
        "delete_action": defaults.delete_action,
        "required_fields": list(defaults.required_fields),
        "address_group_integrity": defaults.address_group_integrity,
        "validity_checks": defaults.validity_checks,
    }
    # The option catalog the form renders from rides alongside.
    assert body["options"]["delete_actions"] == [
        "mark_inactive",
        "tag_deleted",
        "unlink",
    ]
    assert "last_name" in body["options"]["required_field_choices"]


def test_get_reflects_a_persisted_row() -> None:
    SyncSettingsRecord.objects.create(
        singleton_key=SINGLETON_KEY,
        data={
            "auto_create": False,
            "auto_delete": True,
            "delete_action": "unlink",
            "required_fields": ["last_name", "phone"],
        },
    )

    body = _json_body(_drive_get(_make_api(), _request())[0])
    s = body["settings"]
    assert s["auto_create"] is False
    assert s["auto_delete"] is True
    assert s["delete_action"] == "unlink"
    assert s["required_fields"] == ["last_name", "phone"]
    # A key the stored blob omits still falls back to its code default.
    assert s["auto_modify"] is SyncSettings().auto_modify


# ---- PUT, persistence and the round trip --------------------------------


def test_put_persists_and_get_round_trips() -> None:
    put = _json_body(_drive_put(_make_api(), _request(body=_valid_body()))[0])
    # The PUT echoes the stored overlay, exactly what the next read returns.
    assert put["settings"]["auto_create"] is True
    assert put["settings"]["auto_modify"] is False
    assert put["settings"]["delete_action"] == "tag_deleted"
    assert put["settings"]["required_fields"] == ["first_name", "last_name", "email"]

    # Exactly one singleton row, and a fresh GET reads it back.
    assert SyncSettingsRecord.objects.filter(singleton_key=SINGLETON_KEY).count() == 1
    got = _json_body(_drive_get(_make_api(), _request())[0])
    assert got["settings"] == put["settings"]


def test_put_updates_in_place_without_a_second_row() -> None:
    _drive_put(_make_api(), _request(body=_valid_body(auto_create=True)))
    _drive_put(_make_api(), _request(body=_valid_body(auto_create=False)))

    assert SyncSettingsRecord.objects.filter(singleton_key=SINGLETON_KEY).count() == 1
    assert load_sync_settings().auto_create is False


def test_put_drops_blanks_and_duplicates_preserving_order() -> None:
    body = _valid_body(
        required_fields=["phone", "last_name", "phone", "  ", "first_name"]
    )
    put = _json_body(_drive_put(_make_api(), _request(body=body))[0])
    assert put["settings"]["required_fields"] == ["phone", "last_name", "first_name"]


# ---- PUT, the validation refusals ---------------------------------------


def test_put_accepts_required_set_without_last_name() -> None:
    # Last name is a regular field now, dropping it is a valid save, not a refusal.
    body = _valid_body(required_fields=["first_name", "email"])
    put = _json_body(_drive_put(_make_api(), _request(body=body))[0])
    assert put["settings"]["required_fields"] == ["first_name", "email"]
    assert SyncSettingsRecord.objects.count() == 1


def test_put_rejects_non_bool_toggle() -> None:
    body = _valid_body(auto_create="yes")
    responses = _drive_put(_make_api(), _request(body=body))
    assert _status(responses[0]) == HTTPStatus.BAD_REQUEST
    assert "auto create" in _json_body(responses[0])["error"].lower()
    assert SyncSettingsRecord.objects.count() == 0


def test_put_rejects_unknown_delete_action() -> None:
    body = _valid_body(delete_action="purge")
    responses = _drive_put(_make_api(), _request(body=body))
    assert _status(responses[0]) == HTTPStatus.BAD_REQUEST
    assert "delete_action" in _json_body(responses[0])["error"]
    assert SyncSettingsRecord.objects.count() == 0


def test_put_rejects_empty_required_fields() -> None:
    body = _valid_body(required_fields=[])
    responses = _drive_put(_make_api(), _request(body=body))
    assert _status(responses[0]) == HTTPStatus.BAD_REQUEST
    assert "required_fields" in _json_body(responses[0])["error"]
    assert SyncSettingsRecord.objects.count() == 0


def test_put_rejects_unknown_required_field() -> None:
    body = _valid_body(required_fields=["last_name", "favorite_color"])
    responses = _drive_put(_make_api(), _request(body=body))
    assert _status(responses[0]) == HTTPStatus.BAD_REQUEST
    assert "favorite_color" in _json_body(responses[0])["error"]
    assert SyncSettingsRecord.objects.count() == 0


def test_put_rejects_non_object_body() -> None:
    responses = _drive_put(_make_api(), _request(body=["not", "an", "object"]))
    assert _status(responses[0]) == HTTPStatus.BAD_REQUEST
    assert SyncSettingsRecord.objects.count() == 0


def test_put_rejects_unparseable_body() -> None:
    responses = _drive_put(_make_api(), _request(body_raises=ValueError("bad json")))
    assert _status(responses[0]) == HTTPStatus.BAD_REQUEST
    assert SyncSettingsRecord.objects.count() == 0


# ---- The admin gate the routes inherit ----------------------------------


def _credentials(staff_id: str) -> MagicMock:
    creds = MagicMock()
    creds.logged_in_user = {"id": staff_id}
    return creds


@patch.object(StaffSessionAuthMixin, "authenticate", return_value=True)
def test_authenticate_allows_an_admin_staff(_super: MagicMock) -> None:
    api = _make_api()
    type(api).request = PropertyMock(return_value=_request())
    assert api.authenticate(_credentials(_ADMIN_KEY)) is True


@patch.object(StaffSessionAuthMixin, "authenticate", return_value=True)
def test_authenticate_denies_a_non_admin_staff(_super: MagicMock) -> None:
    api = _make_api()
    type(api).request = PropertyMock(return_value=_request())
    assert api.authenticate(_credentials(_OTHER_KEY)) is False


@patch.object(StaffSessionAuthMixin, "authenticate", return_value=False)
def test_authenticate_denies_when_session_fails(_super: MagicMock) -> None:
    api = _make_api()
    type(api).request = PropertyMock(return_value=_request())
    assert api.authenticate(_credentials(_ADMIN_KEY)) is False


# ---- The held row reason thread into the record view --------------------


def test_record_view_threads_hold_reasons() -> None:
    row = IncomingPatientRecord.objects.create(
        external_id="003HOLD01",
        source_object="Contact",
        action="create",
        last_name="Held",
        raw_payload={"Id": "003HOLD01"},
        content_hash="hash-hold-01",
        status="new",
        hold_reasons=["missing required date of birth", "incomplete address"],
    )
    view = _record_view(row, {}, linked=False)
    assert view["hold_reasons"] == [
        "missing required date of birth",
        "incomplete address",
    ]


def test_record_view_hold_reasons_default_empty() -> None:
    row = IncomingPatientRecord.objects.create(
        external_id="003HOLD02",
        source_object="Contact",
        action="create",
        last_name="Clear",
        raw_payload={"Id": "003HOLD02"},
        content_hash="hash-hold-02",
        status="new",
    )
    view = _record_view(row, {}, linked=False)
    assert view["hold_reasons"] == []
