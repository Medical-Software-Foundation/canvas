"""Tests for the field mapping profile routes on SalesforceStatusAPI.

Covers ``GET /field-mapping`` and ``PUT /field-mapping``. The routes drive the
singleton loader and writer directly against the ORM, the same idiom the settings
route tests use, so the HTTP status lives inside the applied SimpleAPI response
effect. They pin the three profile payload shape with and without a secret, the
PUT validation refusals, the active pointer honored by ``_load_field_mapping``,
the empty Salesforce row skipped by the resolver, and that switching the active
pointer without a custom key preserves the stored rows. See journal cnv-941/049.
"""

from __future__ import annotations

import json
from base64 import b64decode
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock, PropertyMock

from salesforce_to_canvas_integration.handlers.status_api import (
    SalesforceStatusAPI,
    _load_field_mapping,
)
from salesforce_to_canvas_integration.services.config import DEFAULT_FIELD_MAPPING

_ADMIN_KEY = "4150cd20de8a470aa570a852859ac87e"
_SECRET_JSON = '{"Contact_First__c": {"target": "first_name"}}'


def _secrets(*, with_secret: bool = False) -> dict[str, str]:
    secrets = {
        "SF_WEBHOOK_SECRET": "whsec",
        "SF_CLIENT_ID": "cid",
        "SF_CLIENT_SECRET": "csec",
        "SF_LOGIN_URL": "https://login.salesforce.com",
        "SF_ADMIN_STAFF_IDS": _ADMIN_KEY,
    }
    if with_secret:
        secrets["SF_FIELD_MAPPING_JSON"] = _SECRET_JSON
    return secrets


def _make_api(*, with_secret: bool = False) -> SalesforceStatusAPI:
    handler = SalesforceStatusAPI.__new__(SalesforceStatusAPI)
    handler.event = MagicMock()
    handler.secrets = _secrets(with_secret=with_secret)
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
    result: list[Any] = api.get_field_mapping()
    return result


def _drive_put(api: SalesforceStatusAPI, request: MagicMock) -> list[Any]:
    type(api).request = PropertyMock(return_value=request)
    result: list[Any] = api.put_field_mapping()
    return result


def _status(effect: Any) -> int:
    return int(json.loads(effect.payload)["status_code"])


def _json_body(effect: Any) -> dict[str, Any]:
    payload = json.loads(effect.payload)
    body: dict[str, Any] = json.loads(b64decode(payload["body"]).decode())
    return body


def _default_rows() -> list[dict[str, str]]:
    return [
        {"salesforce_field": sf, "canvas_target": spec.get("target", "")}
        for sf, spec in DEFAULT_FIELD_MAPPING.items()
    ]


# ---- GET, the three profile payload -------------------------------------


def test_get_no_secret_shape() -> None:
    body = _json_body(_drive_get(_make_api(), _request())[0])
    assert body["active"] == "default"
    assert body["secret_available"] is False
    assert body["profiles"]["secret"] is None
    assert body["profiles"]["default"] == _default_rows()
    # Custom is seeded from the defaults so the editor opens on a real mapping.
    assert body["profiles"]["custom"] == _default_rows()


def test_get_with_secret_shape() -> None:
    body = _json_body(_drive_get(_make_api(with_secret=True), _request())[0])
    assert body["active"] == "secret"
    assert body["secret_available"] is True
    assert body["profiles"]["secret"] == [
        {"salesforce_field": "Contact_First__c", "canvas_target": "first_name"}
    ]


# ---- PUT, persistence and the resolver round trip -----------------------


def test_put_switch_to_default_persists_pointer() -> None:
    api = _make_api(with_secret=True)
    body = _json_body(_drive_put(api, _request(body={"active": "default"}))[0])
    assert body["active"] == "default"
    # The shared resolver now serves the built in defaults.
    assert _load_field_mapping(_secrets(with_secret=True)) == DEFAULT_FIELD_MAPPING


def test_put_custom_persists_and_resolver_skips_empty_rows() -> None:
    custom = [
        {"salesforce_field": "Contact_First__c", "canvas_target": "first_name"},
        {"salesforce_field": "", "canvas_target": "email"},
    ]
    body = _json_body(
        _drive_put(_make_api(), _request(body={"active": "custom", "custom": custom}))[0]
    )
    assert body["active"] == "custom"
    assert body["profiles"]["custom"] == custom
    # The emptied Salesforce cell drops that target from the map the sync reads.
    assert _load_field_mapping(_secrets()) == {
        "Contact_First__c": {"target": "first_name"}
    }


def test_put_custom_omitted_preserves_stored_rows() -> None:
    custom = [{"salesforce_field": "A__c", "canvas_target": "first_name"}]
    _drive_put(_make_api(), _request(body={"active": "custom", "custom": custom}))
    # Switching the active pointer with no custom key must not wipe the rows.
    _drive_put(_make_api(), _request(body={"active": "default"}))
    body = _json_body(_drive_get(_make_api(), _request())[0])
    assert body["active"] == "default"
    assert body["profiles"]["custom"] == custom


# ---- PUT, the validation refusals ---------------------------------------


def test_put_rejects_unknown_active() -> None:
    responses = _drive_put(_make_api(), _request(body={"active": "bogus"}))
    assert _status(responses[0]) == HTTPStatus.BAD_REQUEST
    assert "active" in _json_body(responses[0])["error"]


def test_put_rejects_secret_when_unavailable() -> None:
    responses = _drive_put(_make_api(), _request(body={"active": "secret"}))
    assert _status(responses[0]) == HTTPStatus.BAD_REQUEST
    assert "Secret" in _json_body(responses[0])["error"]


def test_put_rejects_unknown_canvas_target() -> None:
    body = {
        "active": "custom",
        "custom": [{"salesforce_field": "X", "canvas_target": "not_a_field"}],
    }
    responses = _drive_put(_make_api(), _request(body=body))
    assert _status(responses[0]) == HTTPStatus.BAD_REQUEST
    assert "not_a_field" in _json_body(responses[0])["error"]


def test_put_rejects_non_list_custom() -> None:
    responses = _drive_put(
        _make_api(), _request(body={"active": "custom", "custom": "nope"})
    )
    assert _status(responses[0]) == HTTPStatus.BAD_REQUEST


def test_put_rejects_non_object_body() -> None:
    responses = _drive_put(_make_api(), _request(body=["not", "an", "object"]))
    assert _status(responses[0]) == HTTPStatus.BAD_REQUEST
