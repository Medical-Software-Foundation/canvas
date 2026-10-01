"""Tests for the Salesforce OAuth 2.0 PKCE flow.

Drives the helper functions and both OAuth endpoints. Cache interactions use
the FakeCache fixture from conftest. SalesforceClient is mocked so no real
HTTP goes out.
"""

from __future__ import annotations

import json
from base64 import b64decode
from http import HTTPStatus
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from salesforce_to_canvas_integration.handlers.oauth_api import (
    SalesforceOAuthAPI,
    _b64url,
    _build_pkce_pair,
    _callback_url,
    _random_token,
)
from salesforce_to_canvas_integration.services.sf_client import SalesforceError

_SECRETS = {
    "SF_CLIENT_ID": "client-id",
    "SF_CLIENT_SECRET": "client-secret",
    "SF_LOGIN_URL": "https://login.salesforce.com",
    "SF_WEBHOOK_SECRET": "whsecret",
    "SF_ADMIN_STAFF_IDS": "abc123",
}


def _make_api(secrets: dict | None = None) -> SalesforceOAuthAPI:
    handler = SalesforceOAuthAPI.__new__(SalesforceOAuthAPI)
    handler.event = MagicMock()
    handler.secrets = secrets if secrets is not None else dict(_SECRETS)
    handler.environment = {}
    handler._handler = None
    handler._path_pattern = None
    return handler


def _status(effect: object) -> int:
    return int(json.loads(effect.payload)["status_code"])  # type: ignore[attr-defined]


def _json_body(effect: object) -> dict:
    payload = json.loads(effect.payload)  # type: ignore[attr-defined]
    return json.loads(b64decode(payload["body"]).decode())


# --- Helper function tests ---


def test_b64url_excludes_plus_slash_and_padding() -> None:
    raw = bytes([0xFB, 0xFF, 0xFE])
    result = _b64url(raw)
    assert "+" not in result
    assert "/" not in result
    assert "=" not in result


def test_random_token_returns_nonempty_string() -> None:
    result = _random_token(32)
    assert isinstance(result, str)
    assert len(result) > 0


def test_random_token_requires_more_than_sixteen_bytes() -> None:
    result = _random_token(32)
    assert len(result) > 20


def test_build_pkce_pair_returns_two_distinct_strings() -> None:
    verifier, challenge = _build_pkce_pair()
    assert isinstance(verifier, str)
    assert isinstance(challenge, str)
    assert verifier != challenge


def test_callback_url_uses_host_header() -> None:
    request = MagicMock()
    request.headers = {"Host": "test.canvas.com", "X-Forwarded-Proto": "https"}
    result = _callback_url(request)
    assert result == (
        "https://test.canvas.com"
        "/plugin-io/api/salesforce_to_canvas_integration/oauth/callback"
    )


def test_callback_url_falls_back_to_forwarded_host() -> None:
    request = MagicMock()
    request.headers = {
        "X-Forwarded-Host": "proxy.canvas.com",
        "X-Forwarded-Proto": "https",
    }
    result = _callback_url(request)
    assert "proxy.canvas.com" in result


def test_callback_url_raises_when_no_host_header() -> None:
    request = MagicMock()
    request.headers = {}
    with pytest.raises(SalesforceError):
        _callback_url(request)


# --- authenticate ---


def test_authenticate_allows_staff_in_admin_list() -> None:
    from canvas_sdk.handlers.simple_api import StaffSessionAuthMixin

    api = _make_api()
    credentials = MagicMock()
    credentials.logged_in_user = {"id": "abc123"}
    with patch.object(StaffSessionAuthMixin, "authenticate", return_value=True):
        assert api.authenticate(credentials) is True


def test_authenticate_rejects_staff_not_in_admin_list() -> None:
    from canvas_sdk.handlers.simple_api import StaffSessionAuthMixin

    api = _make_api()
    credentials = MagicMock()
    credentials.logged_in_user = {"id": "unknown_staff"}
    with patch.object(StaffSessionAuthMixin, "authenticate", return_value=True):
        assert api.authenticate(credentials) is False


def test_authenticate_returns_false_when_parent_rejects() -> None:
    from canvas_sdk.handlers.simple_api import StaffSessionAuthMixin

    api = _make_api()
    credentials = MagicMock()
    with patch.object(StaffSessionAuthMixin, "authenticate", return_value=False):
        assert api.authenticate(credentials) is False


def test_authenticate_returns_false_on_config_error() -> None:
    from canvas_sdk.handlers.simple_api import StaffSessionAuthMixin

    api = _make_api(secrets={})
    credentials = MagicMock()
    credentials.logged_in_user = {"id": "abc123"}
    with patch.object(StaffSessionAuthMixin, "authenticate", return_value=True):
        assert api.authenticate(credentials) is False


# --- start endpoint ---


def test_start_returns_authorize_url(fake_cache: object) -> None:
    api = _make_api()
    request = MagicMock()
    request.headers = {"Host": "test.canvas.com", "X-Forwarded-Proto": "https"}
    type(api).request = PropertyMock(return_value=request)

    with patch(
        "salesforce_to_canvas_integration.handlers.oauth_api.get_cache",
        return_value=fake_cache,
    ):
        effects = api.start()

    assert len(effects) == 1
    assert _status(effects[0]) == HTTPStatus.OK
    body = _json_body(effects[0])
    assert "authorize_url" in body
    assert "client-id" in body["authorize_url"]


def test_start_stores_state_in_cache(fake_cache: object) -> None:
    api = _make_api()
    request = MagicMock()
    request.headers = {"Host": "test.canvas.com", "X-Forwarded-Proto": "https"}
    type(api).request = PropertyMock(return_value=request)

    with patch(
        "salesforce_to_canvas_integration.handlers.oauth_api.get_cache",
        return_value=fake_cache,
    ):
        api.start()

    matching = [
        k
        for k in fake_cache.store  # type: ignore[attr-defined]
        if k.startswith("oauth:state:")
    ]
    assert len(matching) == 1
    stash = fake_cache.store[matching[0]]  # type: ignore[attr-defined]
    assert "verifier" in stash
    assert "redirect_uri" in stash


def test_start_returns_service_unavailable_on_missing_config(
    fake_cache: object,
) -> None:
    api = _make_api(secrets={})
    request = MagicMock()
    request.headers = {"Host": "test.canvas.com", "X-Forwarded-Proto": "https"}
    type(api).request = PropertyMock(return_value=request)

    with patch(
        "salesforce_to_canvas_integration.handlers.oauth_api.get_cache",
        return_value=fake_cache,
    ):
        effects = api.start()

    assert _status(effects[0]) == HTTPStatus.SERVICE_UNAVAILABLE


def test_start_returns_service_unavailable_when_no_host_header(
    fake_cache: object,
) -> None:
    api = _make_api()
    request = MagicMock()
    request.headers = {}
    type(api).request = PropertyMock(return_value=request)

    with patch(
        "salesforce_to_canvas_integration.handlers.oauth_api.get_cache",
        return_value=fake_cache,
    ):
        effects = api.start()

    assert _status(effects[0]) == HTTPStatus.SERVICE_UNAVAILABLE


# --- callback endpoint ---


def test_callback_returns_bad_request_on_error_param(fake_cache: object) -> None:
    api = _make_api()
    request = MagicMock()
    request.query_params = {
        "error": "access_denied",
        "error_description": "User denied",
    }
    type(api).request = PropertyMock(return_value=request)

    with patch(
        "salesforce_to_canvas_integration.handlers.oauth_api.get_cache",
        return_value=fake_cache,
    ):
        effects = api.callback()

    assert _status(effects[0]) == HTTPStatus.BAD_REQUEST
    assert _json_body(effects[0])["error"] == "User denied"


def test_callback_returns_bad_request_when_code_missing(fake_cache: object) -> None:
    api = _make_api()
    request = MagicMock()
    request.query_params = {"state": "somestate"}
    type(api).request = PropertyMock(return_value=request)

    with patch(
        "salesforce_to_canvas_integration.handlers.oauth_api.get_cache",
        return_value=fake_cache,
    ):
        effects = api.callback()

    assert _status(effects[0]) == HTTPStatus.BAD_REQUEST


def test_callback_returns_bad_request_when_state_missing(fake_cache: object) -> None:
    api = _make_api()
    request = MagicMock()
    request.query_params = {"code": "authcode"}
    type(api).request = PropertyMock(return_value=request)

    with patch(
        "salesforce_to_canvas_integration.handlers.oauth_api.get_cache",
        return_value=fake_cache,
    ):
        effects = api.callback()

    assert _status(effects[0]) == HTTPStatus.BAD_REQUEST


def test_callback_returns_bad_request_when_state_expired(fake_cache: object) -> None:
    api = _make_api()
    request = MagicMock()
    request.query_params = {"code": "authcode", "state": "expired_state"}
    type(api).request = PropertyMock(return_value=request)

    with patch(
        "salesforce_to_canvas_integration.handlers.oauth_api.get_cache",
        return_value=fake_cache,
    ):
        effects = api.callback()

    assert _status(effects[0]) == HTTPStatus.BAD_REQUEST


def test_callback_returns_service_unavailable_on_missing_config(
    fake_cache: object,
) -> None:
    api = _make_api(secrets={"SF_WEBHOOK_SECRET": "s"})
    state = "validstate"
    fake_cache.set(  # type: ignore[attr-defined]
        f"oauth:state:{state}",
        {"verifier": "vcode", "redirect_uri": "https://test.canvas.com/cb"},
    )
    request = MagicMock()
    request.query_params = {"code": "authcode", "state": state}
    type(api).request = PropertyMock(return_value=request)

    with patch(
        "salesforce_to_canvas_integration.handlers.oauth_api.get_cache",
        return_value=fake_cache,
    ):
        effects = api.callback()

    assert _status(effects[0]) == HTTPStatus.SERVICE_UNAVAILABLE


def test_callback_returns_connected_on_success(fake_cache: object) -> None:
    api = _make_api()
    state = "validstate"
    fake_cache.set(  # type: ignore[attr-defined]
        f"oauth:state:{state}",
        {"verifier": "vcode", "redirect_uri": "https://test.canvas.com/cb"},
    )
    request = MagicMock()
    request.query_params = {"code": "authcode", "state": state}
    type(api).request = PropertyMock(return_value=request)

    with patch(
        "salesforce_to_canvas_integration.handlers.oauth_api.get_cache",
        return_value=fake_cache,
    ), patch(
        "salesforce_to_canvas_integration.handlers.oauth_api.SalesforceClient"
    ) as MockClient:
        mock_client = MagicMock()
        MockClient.return_value = mock_client
        effects = api.callback()

    assert _status(effects[0]) == HTTPStatus.OK
    assert _json_body(effects[0])["status"] == "connected"
    mock_client.exchange_authorization_code.assert_called_once_with(
        code="authcode",
        redirect_uri="https://test.canvas.com/cb",
        code_verifier="vcode",
    )


def test_callback_returns_bad_gateway_on_salesforce_exchange_error(
    fake_cache: object,
) -> None:
    api = _make_api()
    state = "validstate"
    fake_cache.set(  # type: ignore[attr-defined]
        f"oauth:state:{state}",
        {"verifier": "vcode", "redirect_uri": "https://test.canvas.com/cb"},
    )
    request = MagicMock()
    request.query_params = {"code": "authcode", "state": state}
    type(api).request = PropertyMock(return_value=request)

    with patch(
        "salesforce_to_canvas_integration.handlers.oauth_api.get_cache",
        return_value=fake_cache,
    ), patch(
        "salesforce_to_canvas_integration.handlers.oauth_api.SalesforceClient"
    ) as MockClient:
        mock_client = MagicMock()
        mock_client.exchange_authorization_code.side_effect = SalesforceError(
            "token exchange failed"
        )
        MockClient.return_value = mock_client
        effects = api.callback()

    assert _status(effects[0]) == HTTPStatus.BAD_GATEWAY


def test_callback_deletes_state_from_cache_after_use(fake_cache: object) -> None:
    api = _make_api()
    state = "validstate"
    cache_key = f"oauth:state:{state}"
    fake_cache.set(  # type: ignore[attr-defined]
        cache_key,
        {"verifier": "vcode", "redirect_uri": "https://test.canvas.com/cb"},
    )
    request = MagicMock()
    request.query_params = {"code": "authcode", "state": state}
    type(api).request = PropertyMock(return_value=request)

    with patch(
        "salesforce_to_canvas_integration.handlers.oauth_api.get_cache",
        return_value=fake_cache,
    ), patch(
        "salesforce_to_canvas_integration.handlers.oauth_api.SalesforceClient",
        return_value=MagicMock(),
    ):
        api.callback()

    assert fake_cache.get(cache_key) is None  # type: ignore[attr-defined]
