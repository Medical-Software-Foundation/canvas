"""Tests for the admin-only webhook configuration SimpleAPI.

Requests go through ``compute()`` so routing, authentication, status codes, and
the SDK's error-response handling are all exercised. The durable AttributeHub
store is replaced with the in-memory backend.
"""

from __future__ import annotations

import json
from base64 import b64decode, b64encode
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import call, patch

import pytest
from canvas_sdk.effects import EffectType
from canvas_sdk.events import EventType

from canvas_event_webhooks.config_page import CONFIG_HTML
from canvas_event_webhooks.config_store import (
    INTERNAL_HOST_ERROR,
    MAX_WEBHOOKS,
    SECRET_PREFIX,
    InMemoryWebhookBackend,
    WebhookConfig,
    WebhookConfigError,
)
from canvas_event_webhooks.events_catalog import all_event_names, catalog_for_ui
from canvas_event_webhooks.handlers.base import (
    _RETRY_ON,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    sign_body,
)
from canvas_event_webhooks.handlers.config_api import (
    ADMIN_STAFF_IDS_VARIABLE,
    TEST_EVENT_NAME,
    WebhookConfigAPI,
)

STAFF_ID = "57f3668ea9f84f3980e772ea8451af38"
OTHER_STAFF_ID = "0000000000000000000000000000beef"
ADMIN_SECRETS = {ADMIN_STAFF_IDS_VARIABLE: STAFF_ID}
LEGACY_SECRETS = {
    "webhook-url": "https://legacy.example.com/canvas",
    "webhook-secret": "cli-secret",
}
JSON_CONTENT_TYPE = "application/json"
AUDIT_MESSAGE = (
    "[Webhooks] Config %s by staff=%s webhook_id=%s host=%s enabled=%s include_details=%s"
)
LOG = "canvas_event_webhooks.handlers.config_api.log"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _event(
    method: str,
    path: str,
    body: dict | list | str | None = None,
    *,
    event_type: int = EventType.SIMPLE_API_REQUEST,
    user_type: str | None = "Staff",
    staff_id: str = STAFF_ID,
    content_type: str | None = JSON_CONTENT_TYPE,
) -> SimpleNamespace:
    """Build a SimpleAPI event the way Canvas delivers it (base64 body, session headers)."""
    if body is None:
        raw = b""
    elif isinstance(body, str):
        raw = body.encode()
    else:
        raw = json.dumps(body).encode()
    headers = {}
    if content_type is not None:
        headers["Content-Type"] = content_type
    if user_type is not None:
        headers["canvas-logged-in-user-id"] = staff_id
        headers["canvas-logged-in-user-type"] = user_type
    return SimpleNamespace(
        type=event_type,
        context={
            "method": method,
            "path": path,
            "query_string": "",
            "body": b64encode(raw).decode(),
            "headers": headers,
        },
    )


def _call(
    method: str,
    path: str,
    body=None,
    *,
    secrets: dict | None = None,
    content_type: str | None = JSON_CONTENT_TYPE,
):
    event = _event(method, path, body, content_type=content_type)
    return WebhookConfigAPI(event=event, secrets=secrets or {}).compute()


def _authenticate(
    path: str,
    *,
    user_type: str | None = "Staff",
    staff_id: str = STAFF_ID,
    secrets: dict | None = None,
) -> int:
    event = _event(
        "GET",
        path,
        event_type=EventType.SIMPLE_API_AUTHENTICATE,
        user_type=user_type,
        staff_id=staff_id,
    )
    effects = WebhookConfigAPI(event=event, secrets=secrets or {}).compute()
    return _response(effects)["status_code"]


def _response(effects) -> dict:
    """Decoded SIMPLE_API_RESPONSE payload; exactly one response is expected."""
    responses = [e for e in effects if e.type == EffectType.SIMPLE_API_RESPONSE]
    assert len(responses) == 1
    return json.loads(responses[0].payload)


def _json(effects) -> tuple[int, dict]:
    payload = _response(effects)
    return payload["status_code"], json.loads(b64decode(payload["body"]))


def _http_request(effects) -> dict:
    requests = [e for e in effects if e.type == EffectType.HTTP_REQUEST]
    assert len(requests) == 1
    return json.loads(requests[0].payload)["data"]


def _saved(**overrides) -> WebhookConfig:
    fields = {
        "id": "wh-1",
        "name": "Production API",
        "url": "https://example.com/hook",
        "secret": f"{SECRET_PREFIX}existing",
        "events": ["PATIENT_CREATED"],
    }
    fields.update(overrides)
    return WebhookConfig(**fields)


def _as_listed(stored: dict) -> dict:
    """How list responses show a stored webhook: no secret, only a hint."""
    secret = stored["secret"]
    hint = "••••" + secret[-4:] if len(secret) >= 16 else ("••••" if secret else "")
    return {**stored, "secret": "", "has_secret": bool(secret), "secret_hint": hint}


@pytest.fixture
def backend() -> InMemoryWebhookBackend:
    return InMemoryWebhookBackend(data=[])


@pytest.fixture
def hub_backend_cls(backend):
    """Replaces the AttributeHub backend; every store construction calls it once."""
    with patch(
        "canvas_event_webhooks.config_store.AttributeHubBackend", return_value=backend
    ) as mock_cls:
        yield mock_cls


# ---------------------------------------------------------------------------
# Authentication and authorization
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "user_type,staff_id,secrets,expected_status,expected_log",
    [
        pytest.param("Staff", STAFF_ID, ADMIN_SECRETS, HTTPStatus.OK, [], id="listed_admin"),
        pytest.param(
            "Staff",
            STAFF_ID,
            {ADMIN_STAFF_IDS_VARIABLE: f" {OTHER_STAFF_ID} , 57F3668E-A9F8-4F39-80E7-72EA8451AF38 "},
            HTTPStatus.OK,
            [],
            id="listed_with_dashes_case_and_spaces",
        ),
        pytest.param(
            "Staff",
            OTHER_STAFF_ID,
            ADMIN_SECRETS,
            HTTPStatus.UNAUTHORIZED,
            [
                call.warning(
                    "[Webhooks] Denied webhook configuration access for staff=%s.", OTHER_STAFF_ID
                )
            ],
            id="staff_not_listed",
        ),
        pytest.param(
            "Staff",
            STAFF_ID,
            {},
            HTTPStatus.UNAUTHORIZED,
            [
                call.warning(
                    "[Webhooks] %s is not set; denying webhook configuration access for staff=%s.",
                    ADMIN_STAFF_IDS_VARIABLE,
                    STAFF_ID,
                )
            ],
            id="allowlist_unset_fails_closed",
        ),
        pytest.param(
            "Staff",
            STAFF_ID,
            {ADMIN_STAFF_IDS_VARIABLE: " , "},
            HTTPStatus.UNAUTHORIZED,
            [
                call.warning(
                    "[Webhooks] %s is not set; denying webhook configuration access for staff=%s.",
                    ADMIN_STAFF_IDS_VARIABLE,
                    STAFF_ID,
                )
            ],
            id="allowlist_blank_fails_closed",
        ),
        pytest.param(
            "Patient", STAFF_ID, ADMIN_SECRETS, HTTPStatus.UNAUTHORIZED, [], id="patient_session"
        ),
        pytest.param(None, STAFF_ID, ADMIN_SECRETS, HTTPStatus.UNAUTHORIZED, [], id="no_session"),
    ],
)
def test_config_data_requires_listed_admin_staff(
    user_type, staff_id, secrets, expected_status, expected_log, hub_backend_cls
):
    with patch(LOG) as mock_log:
        status = _authenticate(
            "/config/webhooks", user_type=user_type, staff_id=staff_id, secrets=secrets
        )

    assert mock_log.mock_calls == expected_log
    assert hub_backend_cls.mock_calls == []
    assert status == expected_status


@pytest.mark.parametrize(
    "user_type,expected_status",
    [
        pytest.param("Staff", HTTPStatus.OK, id="staff"),
        pytest.param("Patient", HTTPStatus.UNAUTHORIZED, id="patient"),
    ],
)
def test_static_page_needs_only_a_staff_session(user_type, expected_status, hub_backend_cls):
    with patch(LOG) as mock_log:
        status = _authenticate("/config/", user_type=user_type, secrets={})

    assert mock_log.mock_calls == []
    assert hub_backend_cls.mock_calls == []
    assert status == expected_status


STATE_CHANGING_ROUTES = [
    pytest.param("POST", "/config/webhooks", id="create"),
    pytest.param("PUT", "/config/webhooks/wh-1", id="update"),
    pytest.param("DELETE", "/config/webhooks/wh-1", id="delete"),
    pytest.param("POST", "/config/webhooks/wh-1/regenerate", id="regenerate"),
    pytest.param("POST", "/config/webhooks/import-legacy", id="import_legacy"),
    pytest.param("POST", "/config/webhooks/wh-1/test", id="test"),
]


@pytest.mark.parametrize("method,path", STATE_CHANGING_ROUTES)
@pytest.mark.parametrize(
    "content_type",
    [
        pytest.param("text/plain", id="text_plain"),
        pytest.param("application/x-www-form-urlencoded", id="form"),
        pytest.param(None, id="missing"),
    ],
)
def test_state_changing_routes_require_json_content_type(
    method, path, content_type, backend, hub_backend_cls
):
    stored = [_saved().to_dict()]
    backend.data = list(stored)
    # Valid JSON, as a cross-site text/plain form could produce.
    body = '{"name": "A", "url": "https://a.example.com/hook", "events": ["PATIENT_CREATED"]}'

    effects = _call(method, path, body, content_type=content_type)

    assert hub_backend_cls.mock_calls == []
    assert len(effects) == 1
    assert _json(effects) == (
        HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
        {"error": "Content-Type must be application/json."},
    )
    assert backend.data == stored


# ---------------------------------------------------------------------------
# Page, catalog, list, reveal
# ---------------------------------------------------------------------------

def test_page_serves_config_html(hub_backend_cls):
    payload = _response(_call("GET", "/config/"))

    assert hub_backend_cls.mock_calls == []
    assert payload["status_code"] == HTTPStatus.OK
    assert payload["headers"] == {"Content-Type": "text/html"}
    assert b64decode(payload["body"]).decode() == CONFIG_HTML


def test_catalog_returns_event_categories(hub_backend_cls):
    status, body = _json(_call("GET", "/config/catalog"))

    assert hub_backend_cls.mock_calls == []
    assert status == HTTPStatus.OK
    assert body == {"categories": catalog_for_ui()}


def test_list_hides_secrets(backend, hub_backend_cls):
    webhook = _saved()
    backend.data = [webhook.to_dict()]

    payload = _response(_call("GET", "/config/webhooks"))

    raw_body = b64decode(payload["body"]).decode()
    assert hub_backend_cls.mock_calls == [call()]
    assert payload["status_code"] == HTTPStatus.OK
    assert json.loads(raw_body) == {
        "webhooks": [
            {**webhook.to_dict(), "secret": "", "has_secret": True, "secret_hint": "••••ting"}
        ],
        "max": MAX_WEBHOOKS,
        "count": 1,
    }
    assert webhook.secret not in raw_body


def test_list_marks_unsigned_legacy_webhook_as_having_no_secret(backend, hub_backend_cls):
    backend.data = None

    status, body = _json(
        _call("GET", "/config/webhooks", secrets={"webhook-url": LEGACY_SECRETS["webhook-url"]})
    )

    assert hub_backend_cls.mock_calls == [call()]
    assert status == HTTPStatus.OK
    [listed] = body["webhooks"]
    # The page disables Copy when has_secret is false.
    assert (listed["id"], listed["secret"], listed["has_secret"], listed["secret_hint"]) == (
        "legacy",
        "",
        False,
        "",
    )


def test_reveal_secret_returns_current_secret(backend, hub_backend_cls):
    webhook = _saved()
    backend.data = [webhook.to_dict()]

    status, body = _json(_call("GET", "/config/webhooks/wh-1/secret"))

    assert hub_backend_cls.mock_calls == [call()]
    assert (status, body) == (HTTPStatus.OK, {"id": "wh-1", "secret": webhook.secret})


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def test_create_saves_webhook_and_returns_new_secret_once(backend, hub_backend_cls):
    status, body = _json(
        _call(
            "POST",
            "/config/webhooks",
            {
                "name": " Production API ",
                "url": " https://example.com/hook ",
                "events": ["PATIENT_CREATED", "PATIENT_CREATED"],
                "include_details": True,
            },
            content_type="application/json; charset=utf-8",
        )
    )

    assert hub_backend_cls.mock_calls == [call(), call()]
    assert status == HTTPStatus.CREATED
    [stored] = backend.data
    created = body["webhook"]
    assert created == {**_as_listed(stored), "secret": stored["secret"]}
    assert created["name"] == "Production API"
    assert created["url"] == "https://example.com/hook"
    assert created["events"] == ["PATIENT_CREATED"]
    assert created["enabled"] is True
    assert created["include_details"] is True
    assert created["legacy"] is False
    assert created["secret"].startswith(SECRET_PREFIX)
    assert body["webhooks"] == [_as_listed(stored)]
    assert body["count"] == 1
    assert body["max"] == MAX_WEBHOOKS
    assert "warning" not in body


@pytest.mark.parametrize(
    "url,expected_error",
    [
        pytest.param("http://example.com/hook", "URL must use HTTPS. HTTP is not allowed.", id="http"),
        pytest.param("https://169.254.169.254/latest/meta-data", INTERNAL_HOST_ERROR, id="metadata"),
        pytest.param("https://127.0.0.1\\@example.com/hook", "URL is not valid.", id="backslash-host"),
    ],
)
def test_create_rejects_disallowed_url(url, expected_error, backend, hub_backend_cls):
    status, body = _json(
        _call("POST", "/config/webhooks", {"name": "Bad", "url": url, "events": ["PATIENT_CREATED"]})
    )

    assert hub_backend_cls.mock_calls == [call()]
    assert status == HTTPStatus.BAD_REQUEST
    assert body == {"error": expected_error}
    assert backend.data == []


def test_create_beyond_limit_conflicts(backend, hub_backend_cls):
    existing = [_saved(id=f"wh-{i}").to_dict() for i in range(MAX_WEBHOOKS)]
    backend.data = list(existing)

    status, body = _json(
        _call(
            "POST",
            "/config/webhooks",
            {"name": "One too many", "url": "https://example.com/4", "events": ["PATIENT_CREATED"]},
        )
    )

    assert hub_backend_cls.mock_calls == [call()]
    assert status == HTTPStatus.CONFLICT
    assert body == {"error": f"A maximum of {MAX_WEBHOOKS} webhooks can be configured."}
    assert backend.data == existing


@pytest.mark.parametrize(
    "method,path",
    [
        pytest.param("POST", "/config/webhooks", id="create"),
        pytest.param("PUT", "/config/webhooks/wh-1", id="update"),
    ],
)
@pytest.mark.parametrize(
    "raw_body,expected_error",
    [
        pytest.param("not json", "Request body must be JSON.", id="not_json"),
        pytest.param('["PATIENT_CREATED"]', "Request body must be a JSON object.", id="json_array"),
    ],
)
def test_malformed_body_is_rejected_before_touching_store(
    method, path, raw_body, expected_error, hub_backend_cls
):
    status, body = _json(_call(method, path, raw_body))

    assert hub_backend_cls.mock_calls == []
    assert status == HTTPStatus.BAD_REQUEST
    assert body == {"error": expected_error}


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

def test_update_applies_every_provided_field(backend, hub_backend_cls):
    webhook = _saved()
    backend.data = [webhook.to_dict()]

    status, body = _json(
        _call(
            "PUT",
            "/config/webhooks/wh-1",
            {
                "name": "Zapier",
                "url": "https://hooks.zapier.com/a",
                "events": ["TASK_CREATED"],
                "enabled": False,
                "include_details": True,
            },
        )
    )

    expected = {
        **webhook.to_dict(),
        "name": "Zapier",
        "url": "https://hooks.zapier.com/a",
        "events": ["TASK_CREATED"],
        "enabled": False,
        "include_details": True,
    }
    assert hub_backend_cls.mock_calls == [call(), call()]
    assert status == HTTPStatus.OK
    assert body == {
        "webhook": _as_listed(expected),
        "webhooks": [_as_listed(expected)],
        "max": MAX_WEBHOOKS,
        "count": 1,
    }
    assert backend.data == [expected]


def test_update_with_partial_body_keeps_other_fields(backend, hub_backend_cls):
    webhook = _saved(include_details=True)
    backend.data = [webhook.to_dict()]

    status, body = _json(_call("PUT", "/config/webhooks/wh-1", {"enabled": False}))

    assert hub_backend_cls.mock_calls == [call(), call()]
    assert status == HTTPStatus.OK
    assert body["webhook"] == _as_listed({**webhook.to_dict(), "enabled": False})


def test_update_unknown_webhook_returns_404(backend, hub_backend_cls):
    status, body = _json(_call("PUT", "/config/webhooks/missing", {"name": "Renamed"}))

    assert hub_backend_cls.mock_calls == [call()]
    assert status == HTTPStatus.NOT_FOUND
    assert body == {"error": "Webhook 'missing' was not found."}


def test_update_with_no_events_returns_400_and_keeps_saved_config(backend, hub_backend_cls):
    saved = [_saved().to_dict()]
    backend.data = list(saved)

    status, body = _json(_call("PUT", "/config/webhooks/wh-1", {"events": []}))

    assert hub_backend_cls.mock_calls == [call()]
    assert status == HTTPStatus.BAD_REQUEST
    assert body == {"error": "Select at least one event."}
    assert backend.data == saved


def test_store_url_warnings_are_returned_to_the_page(backend, hub_backend_cls):
    with patch(
        "canvas_event_webhooks.config_store.validate_webhook_url",
        return_value=(None, "Example warning."),
    ) as mock_validate:
        created_status, created = _json(
            _call(
                "POST",
                "/config/webhooks",
                {"name": "A", "url": "https://a.example.com/hook", "events": ["PATIENT_CREATED"]},
            )
        )
        webhook_id = created["webhook"]["id"]
        updated_status, updated = _json(
            _call("PUT", f"/config/webhooks/{webhook_id}", {"url": "https://b.example.com/hook"})
        )

    assert mock_validate.mock_calls == [
        call("https://a.example.com/hook"),
        call("https://b.example.com/hook"),
    ]
    assert hub_backend_cls.mock_calls == [call(), call(), call(), call()]
    assert (created_status, created["warning"]) == (HTTPStatus.CREATED, "Example warning.")
    assert (updated_status, updated["warning"]) == (HTTPStatus.OK, "Example warning.")


# ---------------------------------------------------------------------------
# Delete, regenerate, import legacy
# ---------------------------------------------------------------------------

def test_delete_removes_webhook(backend, hub_backend_cls):
    backend.data = [_saved().to_dict()]

    status, body = _json(_call("DELETE", "/config/webhooks/wh-1"))

    assert hub_backend_cls.mock_calls == [call(), call()]
    assert status == HTTPStatus.OK
    assert body == {"ok": True, "webhooks": [], "max": MAX_WEBHOOKS, "count": 0}
    assert backend.data == []


def test_regenerate_rotates_and_returns_new_secret_once(backend, hub_backend_cls):
    webhook = _saved()
    backend.data = [webhook.to_dict()]

    status, body = _json(_call("POST", "/config/webhooks/wh-1/regenerate"))

    assert hub_backend_cls.mock_calls == [call(), call()]
    assert status == HTTPStatus.OK
    [stored] = backend.data
    assert stored["secret"] != webhook.secret
    assert stored["secret"].startswith(SECRET_PREFIX)
    assert {**stored, "secret": webhook.secret} == webhook.to_dict()
    assert body["webhook"] == {**_as_listed(stored), "secret": stored["secret"]}
    assert body["webhooks"] == [_as_listed(stored)]


@pytest.mark.parametrize(
    "method,path",
    [
        pytest.param("DELETE", "/config/webhooks/missing", id="delete"),
        pytest.param("POST", "/config/webhooks/missing/regenerate", id="regenerate"),
        pytest.param("GET", "/config/webhooks/missing/secret", id="reveal"),
        pytest.param("POST", "/config/webhooks/missing/test", id="test"),
    ],
)
def test_unknown_webhook_returns_404(method, path, backend, hub_backend_cls):
    effects = _call(method, path)

    assert hub_backend_cls.mock_calls == [call()]
    assert len(effects) == 1
    assert _json(effects) == (HTTPStatus.NOT_FOUND, {"error": "Webhook 'missing' was not found."})


def test_import_legacy_saves_cli_webhook(backend, hub_backend_cls):
    backend.data = None

    status, body = _json(_call("POST", "/config/webhooks/import-legacy", secrets=LEGACY_SECRETS))

    assert hub_backend_cls.mock_calls == [call(), call()]
    assert status == HTTPStatus.CREATED
    [stored] = backend.data
    imported = body["webhook"]
    assert imported == {**_as_listed(stored), "secret": LEGACY_SECRETS["webhook-secret"]}
    # Short CLI secrets are masked without a suffix.
    assert imported["secret_hint"] == "••••"
    assert imported["id"] != "legacy"
    assert imported["legacy"] is False
    assert imported["url"] == LEGACY_SECRETS["webhook-url"]
    assert imported["events"] == all_event_names()
    assert body["webhooks"] == [_as_listed(stored)]


def test_import_legacy_refused_once_ui_config_exists(backend, hub_backend_cls):
    status, body = _json(_call("POST", "/config/webhooks/import-legacy", secrets=LEGACY_SECRETS))

    assert hub_backend_cls.mock_calls == [call()]
    assert status == HTTPStatus.BAD_REQUEST
    assert body == {"error": "UI configuration already exists; legacy CLI secrets are not used."}
    assert backend.data == []


@pytest.mark.parametrize(
    "method,path,body,expected_store_call",
    [
        pytest.param(
            "POST",
            "/config/webhooks",
            {"name": "A", "url": "https://a.example.com/hook", "events": ["PATIENT_CREATED"]},
            call().create(
                name="A",
                url="https://a.example.com/hook",
                events=["PATIENT_CREATED"],
                enabled=True,
                include_details=False,
            ),
            id="create",
        ),
        pytest.param(
            "PUT",
            "/config/webhooks/wh-1",
            {
                "name": "Renamed",
                "url": "https://b.example.com/hook",
                "events": ["TASK_CREATED"],
                "enabled": False,
                "include_details": True,
            },
            call().update(
                "wh-1",
                name="Renamed",
                url="https://b.example.com/hook",
                events=["TASK_CREATED"],
                enabled=False,
                include_details=True,
            ),
            id="update",
        ),
        pytest.param("DELETE", "/config/webhooks/wh-1", None, call().delete("wh-1"), id="delete"),
        pytest.param(
            "POST",
            "/config/webhooks/wh-1/regenerate",
            None,
            call().regenerate_secret("wh-1"),
            id="regenerate",
        ),
        pytest.param(
            "POST",
            "/config/webhooks/import-legacy",
            None,
            call().import_legacy(),
            id="import_legacy",
        ),
    ],
)
def test_generic_store_errors_return_400(method, path, body, expected_store_call):
    with patch("canvas_event_webhooks.handlers.config_api.WebhookConfigStore") as mock_store_cls:
        store = mock_store_cls.return_value
        for name in ("create", "update", "delete", "regenerate_secret", "import_legacy"):
            getattr(store, name).side_effect = WebhookConfigError("Storage unavailable.")

        effects = _call(method, path, body)

    assert mock_store_cls.mock_calls == [call(secrets={}), expected_store_call]
    assert _json(effects) == (HTTPStatus.BAD_REQUEST, {"error": "Storage unavailable."})


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------

def test_every_configuration_action_is_audited_without_secrets(backend, hub_backend_cls):
    backend.data = None

    with patch(LOG) as mock_log:
        _, imported = _json(
            _call("POST", "/config/webhooks/import-legacy", secrets=LEGACY_SECRETS)
        )
        _, created = _json(
            _call(
                "POST",
                "/config/webhooks",
                {
                    "name": "B",
                    "url": "https://b.example.com/hook?token=abc",
                    "events": ["PATIENT_CREATED"],
                    "include_details": True,
                },
            )
        )
        legacy_id = imported["webhook"]["id"]
        webhook_id = created["webhook"]["id"]
        _call("PUT", f"/config/webhooks/{webhook_id}", {"enabled": False})
        _call("POST", f"/config/webhooks/{webhook_id}/regenerate")
        _call("POST", f"/config/webhooks/{webhook_id}/test")
        _call("GET", f"/config/webhooks/{webhook_id}/secret")
        _call("DELETE", f"/config/webhooks/{webhook_id}")

    def audit(action, audited_id, host, enabled, include_details):
        return call.info(AUDIT_MESSAGE, action, STAFF_ID, audited_id, host, enabled, include_details)

    assert mock_log.mock_calls == [
        audit("legacy_imported", legacy_id, "legacy.example.com", True, False),
        audit("created", webhook_id, "b.example.com", True, True),
        audit("updated", webhook_id, "b.example.com", False, True),
        audit("secret_regenerated", webhook_id, "b.example.com", False, True),
        audit("test_sent", webhook_id, "b.example.com", False, True),
        audit("secret_revealed", webhook_id, "b.example.com", False, True),
        audit("deleted", webhook_id, "b.example.com", False, True),
    ]
    assert hub_backend_cls.mock_calls == [call()] * 12


# ---------------------------------------------------------------------------
# Test delivery
# ---------------------------------------------------------------------------

def test_test_webhook_queues_signed_async_delivery(backend, hub_backend_cls):
    webhook = _saved()
    backend.data = [webhook.to_dict()]

    effects = _call("POST", "/config/webhooks/wh-1/test")

    assert hub_backend_cls.mock_calls == [call()]
    assert len(effects) == 2
    status, body = _json(effects)
    assert status == HTTPStatus.OK
    assert body["ok"] is True
    assert "canvas logs" in body["message"]
    assert "warning" not in body

    request = _http_request(effects)
    assert request["url"] == webhook.url
    assert request["method"].upper() == "POST"
    assert request["retry_on_status_codes"] == _RETRY_ON
    sent = json.loads(request["body"])
    assert sent["event"] == TEST_EVENT_NAME
    assert sent["test"] is True
    assert sent["source"] == "canvas"
    assert "description" not in sent
    assert "data" not in sent
    headers = request["headers"]
    assert headers["Content-Type"] == "application/json"
    timestamp = int(headers[TIMESTAMP_HEADER])
    assert headers[SIGNATURE_HEADER] == sign_body(webhook.secret, request["body"], timestamp)


def test_test_webhook_includes_sample_details_when_enabled(backend, hub_backend_cls):
    backend.data = [_saved(include_details=True).to_dict()]

    effects = _call("POST", "/config/webhooks/wh-1/test")

    assert hub_backend_cls.mock_calls == [call()]
    sent = json.loads(_http_request(effects)["body"])
    assert sent["description"] == (
        "Canvas — Test event from Canvas Event Webhooks (names and details enabled)."
    )
    assert sent["data"] == {"record_type": "test"}


@pytest.mark.parametrize(
    "stored_webhook,expected_error",
    [
        pytest.param(
            _saved(url="http://example.com/hook"),
            "URL must use HTTPS. HTTP is not allowed.",
            id="http_url",
        ),
        pytest.param(
            _saved(url="https://10.0.0.5/hook"),
            INTERNAL_HOST_ERROR,
            id="internal_url",
        ),
        pytest.param(
            _saved(secret=""),
            "This webhook has no secret to sign the test with.",
            id="unsigned",
        ),
    ],
)
def test_test_webhook_refuses_undeliverable_config(
    stored_webhook, expected_error, backend, hub_backend_cls
):
    backend.data = [stored_webhook.to_dict()]

    effects = _call("POST", "/config/webhooks/wh-1/test")

    assert hub_backend_cls.mock_calls == [call()]
    # Only the error response: no HTTP request is queued.
    assert len(effects) == 1
    assert _json(effects) == (HTTPStatus.BAD_REQUEST, {"error": expected_error})


def test_test_webhook_forwards_url_warning(backend, hub_backend_cls):
    backend.data = [_saved().to_dict()]

    with patch(
        "canvas_event_webhooks.handlers.config_api.validate_webhook_url",
        return_value=(None, "Example warning."),
    ) as mock_validate:
        effects = _call("POST", "/config/webhooks/wh-1/test")

    assert mock_validate.mock_calls == [call("https://example.com/hook")]
    assert hub_backend_cls.mock_calls == [call()]
    status, body = _json(effects)
    assert status == HTTPStatus.OK
    assert body["warning"] == "Example warning."
