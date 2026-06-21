"""Tests for GoogleAuth token caching + JWT-bearer exchange (signing mocked out)."""

from types import SimpleNamespace

import pytest

from gcal_sync.google.auth import GoogleAuth, GoogleAuthError

SA = '{"client_email": "svc@x.iam", "private_key": "KEY"}'


def test_get_access_token_returns_cached(mocker):
    cache = mocker.patch("gcal_sync.google.auth.get_cache").return_value
    cache.get.return_value = "cached-token"
    assert GoogleAuth(SA).get_access_token("sub@x") == "cached-token"


def test_get_access_token_requires_subject(mocker):
    mocker.patch("gcal_sync.google.auth.get_cache")
    with pytest.raises(GoogleAuthError):
        GoogleAuth(SA).get_access_token("")


def test_get_access_token_mints_and_caches(mocker):
    cache = mocker.patch("gcal_sync.google.auth.get_cache").return_value
    cache.get.return_value = None
    mocker.patch("gcal_sync.google.auth.build_assertion", return_value="signed-jwt")
    http = mocker.patch("gcal_sync.google.auth.Http").return_value
    http.post.return_value = SimpleNamespace(
        status_code=200, json=lambda: {"access_token": "fresh-token", "expires_in": 3600}, text=""
    )
    assert GoogleAuth(SA).get_access_token("sub@x") == "fresh-token"
    cache.set.assert_called_once()


def test_exchange_failure_raises(mocker):
    cache = mocker.patch("gcal_sync.google.auth.get_cache").return_value
    cache.get.return_value = None
    mocker.patch("gcal_sync.google.auth.build_assertion", return_value="signed-jwt")
    http = mocker.patch("gcal_sync.google.auth.Http").return_value
    http.post.return_value = SimpleNamespace(status_code=400, json=lambda: {}, text="invalid_grant")
    with pytest.raises(GoogleAuthError):
        GoogleAuth(SA).get_access_token("sub@x")


def test_parse_service_account_fails_closed_when_missing():
    with pytest.raises(GoogleAuthError):
        GoogleAuth(None)
