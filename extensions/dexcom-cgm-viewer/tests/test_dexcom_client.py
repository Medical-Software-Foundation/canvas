"""Sync HTTP client around the Dexcom v3 API."""

from __future__ import annotations

import datetime as dt
from unittest.mock import MagicMock

import pytest

from dexcom_cgm_viewer.services.dexcom_client import (
    DexcomAPIError,
    DexcomAuthError,
    DexcomClient,
    _format_dexcom_dt,
)


def _client(env: str = "sandbox") -> tuple[DexcomClient, MagicMock]:
    http = MagicMock()
    client = DexcomClient(
        environment=env,
        client_id="cid",
        client_secret="sec",
        redirect_uri="https://canvas.example.com/plugin-io/api/dexcom_cgm_viewer/callback",
        http=http,
    )
    return client, http


def _resp(status: int, payload: object = None, text: str = "") -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.json.return_value = payload
    response.text = text or (str(payload) if payload is not None else "")
    return response


def test_authorize_url_uses_environment_base() -> None:
    sandbox, _ = _client("sandbox")
    prod, _ = _client("production")
    assert sandbox.base_url == "https://sandbox-api.dexcom.com"
    assert prod.base_url == "https://api.dexcom.com"
    url = sandbox.authorize_url("state-value")
    assert url.startswith("https://sandbox-api.dexcom.com/v3/oauth2/login?")
    assert "client_id=cid" in url
    assert "scope=offline_access" in url
    assert "state=state-value" in url


def test_exchange_code_returns_token_set() -> None:
    client, http = _client()
    http.post.return_value = _resp(200, {
        "access_token": "AT", "refresh_token": "RT", "expires_in": 7200,
        "token_type": "Bearer", "userId": "DEX-USER",
    })
    tokens = client.exchange_code("auth-code")
    assert tokens.access_token == "AT"
    assert tokens.refresh_token == "RT"
    assert tokens.expires_in == 7200
    assert tokens.dexcom_user_id == "DEX-USER"
    assert (tokens.expires_at - dt.datetime.now(dt.timezone.utc)).total_seconds() > 0
    # canvas_sdk.utils.http.Http joins against its base_url internally, so
    # DexcomClient now passes a path-only URL.
    posted_url = http.post.call_args.args[0]
    assert posted_url == "/v3/oauth2/token"
    assert http.post.call_args.kwargs["data"]["grant_type"] == "authorization_code"


def test_exchange_code_raises_auth_error_on_4xx_credentials_failure() -> None:
    client, http = _client()
    http.post.return_value = _resp(401, text="bad code")
    with pytest.raises(DexcomAuthError):
        client.exchange_code("nope")


def test_token_request_raises_api_error_on_5xx() -> None:
    client, http = _client()
    http.post.return_value = _resp(503, text="dexcom down")
    with pytest.raises(DexcomAPIError) as excinfo:
        client.refresh("RT")
    assert excinfo.value.status_code == 503


def test_refresh_returns_rotated_tokens() -> None:
    client, http = _client()
    http.post.return_value = _resp(200, {
        "access_token": "AT2", "refresh_token": "RT2", "expires_in": 7200,
    })
    tokens = client.refresh("RT1")
    assert tokens.access_token == "AT2"
    assert tokens.refresh_token == "RT2"
    assert http.post.call_args.kwargs["data"]["refresh_token"] == "RT1"
    assert http.post.call_args.kwargs["data"]["grant_type"] == "refresh_token"


def test_fetch_egvs_strips_records_field() -> None:
    client, http = _client()
    http.get.return_value = _resp(200, {"records": [{"value": 142}, {"value": 130}]})
    start = dt.datetime(2026, 5, 1, 0, 0, tzinfo=dt.timezone.utc)
    end = dt.datetime(2026, 5, 2, 0, 0, tzinfo=dt.timezone.utc)
    rows = client.fetch_egvs("ACCESS", start, end)
    assert len(rows) == 2
    # canvas_sdk.utils.http.Http.get takes no ``params`` kwarg, so query
    # params are encoded into the URL by DexcomClient before joining.
    sent_url = http.get.call_args.args[0]
    assert sent_url.startswith("/v3/users/self/egvs?")
    assert "startDate=2026-05-01T00%3A00%3A00" in sent_url
    assert "endDate=2026-05-02T00%3A00%3A00" in sent_url
    assert http.get.call_args.kwargs["headers"]["Authorization"] == "Bearer ACCESS"


def test_fetch_data_range_calls_path_without_query_params() -> None:
    client, http = _client()
    http.get.return_value = _resp(200, {"egvs": {"start": "x", "end": "y"}})
    client.fetch_data_range("AT")
    sent_url = http.get.call_args.args[0]
    assert sent_url == "/v3/users/self/dataRange"


def test_fetch_egvs_returns_empty_when_no_records_field() -> None:
    client, http = _client()
    http.get.return_value = _resp(200, {})
    rows = client.fetch_egvs("AT", dt.datetime.now(dt.timezone.utc),
                             dt.datetime.now(dt.timezone.utc))
    assert rows == []


def test_fetch_egvs_returns_empty_when_response_is_not_a_dict() -> None:
    client, http = _client()
    http.get.return_value = _resp(200, ["unexpected"])
    rows = client.fetch_egvs("AT", dt.datetime.now(dt.timezone.utc),
                             dt.datetime.now(dt.timezone.utc))
    assert rows == []


def test_fetch_egvs_401_raises_auth_error() -> None:
    client, http = _client()
    http.get.return_value = _resp(401, text="expired")
    with pytest.raises(DexcomAuthError):
        client.fetch_egvs("AT", dt.datetime.now(dt.timezone.utc),
                          dt.datetime.now(dt.timezone.utc))


def test_fetch_egvs_5xx_raises_api_error() -> None:
    client, http = _client()
    http.get.return_value = _resp(500, text="boom")
    with pytest.raises(DexcomAPIError):
        client.fetch_egvs("AT", dt.datetime.now(dt.timezone.utc),
                          dt.datetime.now(dt.timezone.utc))


def test_fetch_data_range_returns_dict() -> None:
    client, http = _client()
    http.get.return_value = _resp(200, {"egvs": {"start": "x", "end": "y"}})
    data = client.fetch_data_range("AT")
    assert data == {"egvs": {"start": "x", "end": "y"}}


def test_fetch_data_range_returns_empty_dict_for_unexpected_shape() -> None:
    client, http = _client()
    http.get.return_value = _resp(200, ["nope"])
    assert client.fetch_data_range("AT") == {}


def test_format_dexcom_dt_normalizes_naive() -> None:
    naive = dt.datetime(2026, 5, 1, 12, 30, 45)
    assert _format_dexcom_dt(naive) == "2026-05-01T12:30:45"
