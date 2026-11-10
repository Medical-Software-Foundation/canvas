"""Tests for the Oura API v2 HTTP client, against a mocked transport."""

import datetime as dt
from typing import Any
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse

import pytest

from oura_ring_viewer.services.oura_client import (
    OuraAPIError,
    OuraAuthError,
    OuraClient,
    OuraForbiddenError,
)
from oura_ring_viewer.services.settings import MAX_PAGES

REDIRECT = "https://canvas.example.com/plugin-io/api/oura_ring_viewer/callback"
START = dt.date(2026, 10, 1)
END = dt.date(2026, 10, 14)


def _client(env: str = "sandbox") -> tuple[OuraClient, MagicMock]:
    http = MagicMock()
    client = OuraClient(
        environment=env,
        client_id="cid",
        client_secret="sec",
        redirect_uri=REDIRECT,
        http=http,
    )
    return client, http


def _resp(status: int, payload: Any = None, text: str = "") -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.json.return_value = payload
    response.text = text or ("" if payload is None else str(payload))
    return response


def _token_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "access_token": "AT",
        "refresh_token": "RT",
        "expires_in": 86_400,
        "token_type": "bearer",
        "scope": "daily spo2",
    }
    payload.update(overrides)
    return payload


def _get_url(http: MagicMock, call: int = 0) -> tuple[str, dict[str, list[str]]]:
    url = http.get.call_args_list[call].args[0]
    parsed = urlparse(url)
    return parsed.path, parse_qs(parsed.query)


class TestAuthorizeUrl:
    def test_points_at_oura_hosted_consent_with_minimal_scope(self) -> None:
        client, _ = _client()
        url = urlparse(client.authorize_url("signed-state"))
        query = parse_qs(url.query)
        assert f"{url.scheme}://{url.netloc}{url.path}" == "https://cloud.ouraring.com/oauth/authorize"
        assert query == {
            "response_type": ["code"],
            "client_id": ["cid"],
            "redirect_uri": [REDIRECT],
            "scope": ["daily spo2"],
            "state": ["signed-state"],
        }

    def test_never_requests_personal_or_intraday_scopes(self) -> None:
        client, _ = _client()
        scope = parse_qs(urlparse(client.authorize_url("s")).query)["scope"][0].split()
        assert not {"personal", "email", "heartrate", "workout"} & set(scope)


class TestEnvironment:
    def test_sandbox_and_production_paths(self) -> None:
        assert _client("sandbox")[0].collection_path == "/v2/sandbox/usercollection"
        assert _client("production")[0].collection_path == "/v2/usercollection"

    def test_an_unknown_environment_is_refused(self) -> None:
        with pytest.raises(ValueError):
            _client("prod")


class TestTokenRequests:
    def test_exchange_code_posts_form_and_returns_tokens(self) -> None:
        client, http = _client()
        http.post.return_value = _resp(200, _token_payload())
        tokens = client.exchange_code("auth-code")

        assert (tokens.access_token, tokens.refresh_token) == ("AT", "RT")
        assert tokens.expires_in == 86_400
        assert tokens.scope == "daily spo2"
        assert tokens.expires_at > dt.datetime.now(dt.UTC)
        assert http.post.call_args.args[0] == "/oauth/token"
        body = http.post.call_args.kwargs["data"]
        assert body["grant_type"] == "authorization_code"
        assert body["code"] == "auth-code"
        assert body["redirect_uri"] == REDIRECT

    def test_refresh_sends_refresh_grant(self) -> None:
        client, http = _client()
        http.post.return_value = _resp(200, _token_payload(refresh_token="RT2"))
        assert client.refresh("RT1").refresh_token == "RT2"
        body = http.post.call_args.kwargs["data"]
        assert body["grant_type"] == "refresh_token"
        assert body["refresh_token"] == "RT1"

    @pytest.mark.parametrize("status", [400, 401, 403])
    def test_rejected_token_request_is_an_auth_error(self, status: int) -> None:
        client, http = _client()
        http.post.return_value = _resp(status, text="invalid_grant")
        with pytest.raises(OuraAuthError):
            client.refresh("RT")

    def test_server_error_on_token_request_is_an_api_error(self) -> None:
        client, http = _client()
        http.post.return_value = _resp(503, text="down")
        with pytest.raises(OuraAPIError) as excinfo:
            client.exchange_code("code")
        assert excinfo.value.status_code == 503

    @pytest.mark.parametrize("missing", ["access_token", "refresh_token"])
    def test_response_missing_a_token_is_refused_not_stored(self, missing: str) -> None:
        """Persisting an empty single-use refresh token would lock the patient out."""
        client, http = _client()
        http.post.return_value = _resp(200, _token_payload(**{missing: ""}))
        with pytest.raises(OuraAPIError):
            client.refresh("RT")

    def test_non_object_token_response_is_refused(self) -> None:
        client, http = _client()
        http.post.return_value = _resp(200, ["not", "an", "object"])
        with pytest.raises(OuraAPIError):
            client.exchange_code("code")

    @pytest.mark.parametrize("expires_in", [None, "soon", -100])
    def test_bad_expiry_is_treated_as_already_expired(self, expires_in: Any) -> None:
        client, http = _client()
        http.post.return_value = _resp(200, _token_payload(expires_in=expires_in))
        assert client.exchange_code("code").expires_in == 0


class TestFetchCollection:
    def test_requests_the_inclusive_window_with_bearer_auth(self) -> None:
        client, http = _client()
        http.get.return_value = _resp(200, {"data": [{"day": "2026-10-01"}], "next_token": None})
        records = client.fetch_collection("AT", "daily_readiness", START, END)

        assert records == [{"day": "2026-10-01"}]
        path, query = _get_url(http)
        assert path == "/v2/sandbox/usercollection/daily_readiness"
        assert query == {"start_date": ["2026-10-01"], "end_date": ["2026-10-15"]}
        assert http.get.call_args.kwargs["headers"] == {"Authorization": "Bearer AT"}

    def test_follows_next_token_across_pages(self) -> None:
        client, http = _client()
        http.get.side_effect = [
            _resp(200, {"data": [{"day": "2026-10-01"}], "next_token": "page2"}),
            _resp(200, {"data": [{"day": "2026-10-02"}], "next_token": None}),
        ]
        records = client.fetch_collection("AT", "daily_sleep", START, END)
        assert [r["day"] for r in records] == ["2026-10-01", "2026-10-02"]
        assert _get_url(http, 1)[1]["next_token"] == ["page2"]

    def test_stops_when_oura_repeats_the_same_next_token(self) -> None:
        client, http = _client()
        http.get.return_value = _resp(200, {"data": [], "next_token": "stuck"})
        client.fetch_collection("AT", "daily_sleep", START, END)
        assert http.get.call_count == 2

    def test_page_cap_bounds_a_runaway_paginator(self) -> None:
        client, http = _client()
        http.get.side_effect = [
            _resp(200, {"data": [], "next_token": f"t{i}"}) for i in range(MAX_PAGES + 5)
        ]
        client.fetch_collection("AT", "daily_sleep", START, END)
        assert http.get.call_count == MAX_PAGES

    @pytest.mark.parametrize("page", [None, [], "text", {"data": "nope"}, {"data": [1, None, "x"]}])
    def test_malformed_pages_yield_no_records(self, page: Any) -> None:
        client, http = _client()
        http.get.return_value = _resp(200, page)
        assert client.fetch_collection("AT", "daily_sleep", START, END) == []

    def test_401_is_an_auth_error_for_refresh_and_retry(self) -> None:
        client, http = _client()
        http.get.return_value = _resp(401, text="expired")
        with pytest.raises(OuraAuthError):
            client.fetch_collection("AT", "daily_sleep", START, END)

    def test_403_is_forbidden_not_an_auth_error(self) -> None:
        """A 403 must not trigger a refresh: the token is fine, the data is not available."""
        client, http = _client()
        http.get.return_value = _resp(403, text="scope not granted")
        with pytest.raises(OuraForbiddenError) as excinfo:
            client.fetch_collection("AT", "daily_spo2", START, END)
        assert not isinstance(excinfo.value, OuraAuthError)
        assert isinstance(excinfo.value, OuraAPIError)

    @pytest.mark.parametrize("status", [404, 429, 500, 502])
    def test_other_errors_are_api_errors(self, status: int) -> None:
        client, http = _client()
        http.get.return_value = _resp(status, text="nope")
        with pytest.raises(OuraAPIError) as excinfo:
            client.fetch_collection("AT", "daily_sleep", START, END)
        assert excinfo.value.status_code == status
        assert not isinstance(excinfo.value, OuraForbiddenError)
