"""Tests for the Salesforce HTTP client (token refresh + writeback)."""

from __future__ import annotations

import time
from typing import Any

import pytest

from salesforce_to_canvas_integration.services.sf_client import (
    DEFAULT_EXPIRES_IN,
    SalesforceClient,
    SalesforceError,
    SalesforceNotConnectedError,
    SalesforceReconnectRequiredError,
)
from salesforce_to_canvas_integration.services.storage import StoredTokens, TokenStore

from tests.conftest import FakeCache


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any] | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = "" if payload is None else str(payload)

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeHttp:
    """Records calls and returns scripted responses."""

    def __init__(self) -> None:
        self.posts: list[tuple[str, dict[str, Any]]] = []
        self.patches: list[tuple[str, dict[str, Any]]] = []
        self.post_responses: list[FakeResponse] = []
        self.patch_responses: list[FakeResponse] = []

    def post(
        self,
        url: str,
        data: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        **kw: Any,
    ) -> FakeResponse:
        self.posts.append((url, dict(data or {})))
        return self.post_responses.pop(0)

    def patch(
        self,
        url: str,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        **kw: Any,
    ) -> FakeResponse:
        self.patches.append((url, dict(json or {})))
        return self.patch_responses.pop(0)

    def get(self, url: str, headers: dict[str, str] | None = None, **kw: Any) -> FakeResponse:
        raise NotImplementedError


def _client(http: FakeHttp, tokens: TokenStore) -> SalesforceClient:
    return SalesforceClient(
        http=http,
        tokens=tokens,
        login_url="https://login.salesforce.com",
        client_id="cid",
        client_secret="csecret",
    )


def test_exchange_authorization_code_persists_tokens() -> None:
    cache = FakeCache()
    tokens = TokenStore(cache)
    http = FakeHttp()
    http.post_responses.append(
        FakeResponse(
            200,
            {
                "access_token": "atk",
                "refresh_token": "rtk",
                "instance_url": "https://my.salesforce.com/",
                "issued_at": "1700000000000",
                "expires_in": 7200,
            },
        )
    )

    client = _client(http, tokens)
    result = client.exchange_authorization_code(
        code="code-1",
        redirect_uri="https://canvas/callback",
        code_verifier="verifier",
    )

    stored = tokens.load()
    assert stored is not None
    assert stored.access_token == "atk"
    assert stored.refresh_token == "rtk"
    assert stored.instance_url == "https://my.salesforce.com"
    assert result.expires_at - result.issued_at == 7200


def test_exchange_authorization_code_raises_on_http_error() -> None:
    http = FakeHttp()
    http.post_responses.append(FakeResponse(400, {"error": "invalid_grant"}))
    with pytest.raises(SalesforceError):
        _client(http, TokenStore(FakeCache())).exchange_authorization_code(
            code="bad", redirect_uri="https://canvas/callback"
        )


def test_refresh_failure_clears_tokens_and_raises_reconnect() -> None:
    cache = FakeCache()
    tokens = TokenStore(cache)
    tokens.save(
        StoredTokens(
            access_token="old",
            refresh_token="rtk",
            instance_url="https://my.salesforce.com",
            issued_at=0.0,
            expires_at=0.0,
        )
    )

    http = FakeHttp()
    http.post_responses.append(FakeResponse(401, {"error": "invalid_grant"}))
    client = _client(http, tokens)

    with pytest.raises(SalesforceReconnectRequiredError):
        client.refresh()
    assert tokens.load() is None


def test_write_canvas_id_refreshes_on_401_then_succeeds() -> None:
    cache = FakeCache()
    tokens = TokenStore(cache)
    tokens.save(
        StoredTokens(
            access_token="expired",
            refresh_token="rtk",
            instance_url="https://my.salesforce.com",
            issued_at=time.time(),
            expires_at=time.time() + DEFAULT_EXPIRES_IN,
        )
    )

    http = FakeHttp()
    http.patch_responses.extend(
        [
            FakeResponse(401, {"error": "INVALID_SESSION"}),
            FakeResponse(204, None),
        ]
    )
    http.post_responses.append(
        FakeResponse(
            200,
            {
                "access_token": "new-token",
                "refresh_token": "rtk",
                "instance_url": "https://my.salesforce.com",
                "issued_at": str(int(time.time() * 1000)),
                "expires_in": 3600,
            },
        )
    )

    _client(http, tokens).write_canvas_id(
        sobject="Contact",
        sf_record_id="003xx0",
        canvas_patient_id="canvas-1",
    )

    # First PATCH (401), refresh POST, second PATCH (204)
    assert len(http.patches) == 2
    assert http.patches[0][1] == {"Canvas_Patient_ID__c": "canvas-1"}


def test_write_canvas_id_raises_when_not_connected() -> None:
    http = FakeHttp()
    with pytest.raises(SalesforceNotConnectedError):
        _client(http, TokenStore(FakeCache())).write_canvas_id(
            sobject="Contact",
            sf_record_id="003",
            canvas_patient_id="canvas-1",
        )
