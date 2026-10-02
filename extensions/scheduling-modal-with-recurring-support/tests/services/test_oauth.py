from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from scheduling_modal_with_recurring_support.services.oauth import (
    DEFAULT_TTL_SECONDS,
    EXPIRY_SAFETY_MARGIN_SECONDS,
    OAuthToken,
    _cache_key,
    acquire_token,
)


def _make_ok_response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.ok = True
    resp.status_code = 200
    resp.json.return_value = payload
    return resp


def _make_error_response(status: int, text: str) -> MagicMock:
    resp = MagicMock()
    resp.ok = False
    resp.status_code = status
    resp.text = text
    return resp


def _empty_cache() -> MagicMock:
    cache = MagicMock()
    cache.get.return_value = None
    return cache


def test_cache_key_format() -> None:
    assert _cache_key("https://host.canvasmedical.com/", "cid") == "oauth_token::https://host.canvasmedical.com::cid"


def test_cache_key_no_trailing_slash() -> None:
    assert _cache_key("https://host.canvasmedical.com", "cid") == "oauth_token::https://host.canvasmedical.com::cid"


def test_acquire_token_success() -> None:
    mock_http = MagicMock()
    mock_cache = _empty_cache()
    mock_response = _make_ok_response({"access_token": "tok123", "token_type": "Bearer"})
    mock_http.post.return_value = mock_response

    with (
        patch("scheduling_modal_with_recurring_support.services.oauth.get_cache", return_value=mock_cache),
        patch("scheduling_modal_with_recurring_support.services.oauth.Http", return_value=mock_http),
    ):
        result = acquire_token(
            instance_url="https://test.canvasmedical.com",
            client_id="cid",
            client_secret="csecret",
        )

    assert result == OAuthToken(access_token="tok123", token_type="Bearer")
    mock_http.post.assert_called_once_with(
        "https://test.canvasmedical.com/auth/token/",
        data={
            "grant_type": "client_credentials",
            "client_id": "cid",
            "client_secret": "csecret",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    mock_cache.set.assert_called_once()


def test_acquire_token_strips_trailing_slash() -> None:
    mock_http = MagicMock()
    mock_cache = _empty_cache()
    mock_response = _make_ok_response({"access_token": "t"})
    mock_http.post.return_value = mock_response

    with (
        patch("scheduling_modal_with_recurring_support.services.oauth.get_cache", return_value=mock_cache),
        patch("scheduling_modal_with_recurring_support.services.oauth.Http", return_value=mock_http),
    ):
        acquire_token("https://host.canvasmedical.com/", "c", "s")

    mock_http.post.assert_called_once_with(
        "https://host.canvasmedical.com/auth/token/",
        data={"grant_type": "client_credentials", "client_id": "c", "client_secret": "s"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )


def test_acquire_token_default_token_type() -> None:
    mock_http = MagicMock()
    mock_cache = _empty_cache()
    mock_response = _make_ok_response({"access_token": "t"})
    mock_http.post.return_value = mock_response

    with (
        patch("scheduling_modal_with_recurring_support.services.oauth.get_cache", return_value=mock_cache),
        patch("scheduling_modal_with_recurring_support.services.oauth.Http", return_value=mock_http),
    ):
        result = acquire_token("https://host.canvasmedical.com", "c", "s")

    assert result.token_type == "Bearer"


def test_acquire_token_failure_raises() -> None:
    mock_http = MagicMock()
    mock_cache = _empty_cache()
    mock_response = _make_error_response(401, "Unauthorized")
    mock_http.post.return_value = mock_response

    with (
        patch("scheduling_modal_with_recurring_support.services.oauth.get_cache", return_value=mock_cache),
        patch("scheduling_modal_with_recurring_support.services.oauth.Http", return_value=mock_http),
    ):
        with pytest.raises(RuntimeError, match="OAuth token request failed: 401"):
            acquire_token("https://host.canvasmedical.com", "c", "s")

    mock_http.post.assert_called_once_with(
        "https://host.canvasmedical.com/auth/token/",
        data={"grant_type": "client_credentials", "client_id": "c", "client_secret": "s"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    mock_cache.set.assert_not_called()


def test_acquire_token_cache_hit_returns_without_http() -> None:
    mock_cache = MagicMock()
    mock_cache.get.return_value = {"access_token": "cached_tok", "token_type": "Bearer"}

    with (
        patch("scheduling_modal_with_recurring_support.services.oauth.get_cache", return_value=mock_cache),
        patch("scheduling_modal_with_recurring_support.services.oauth.Http") as mock_http_cls,
    ):
        result = acquire_token("https://host.canvasmedical.com", "c", "s")

    assert result == OAuthToken(access_token="cached_tok", token_type="Bearer")
    mock_http_cls.assert_not_called()
    mock_cache.set.assert_not_called()


def test_acquire_token_cache_hit_uses_default_token_type_when_missing() -> None:
    mock_cache = MagicMock()
    mock_cache.get.return_value = {"access_token": "tok"}

    with (
        patch("scheduling_modal_with_recurring_support.services.oauth.get_cache", return_value=mock_cache),
        patch("scheduling_modal_with_recurring_support.services.oauth.Http"),
    ):
        result = acquire_token("https://host.canvasmedical.com", "c", "s")

    assert result.token_type == "Bearer"


def test_acquire_token_uses_expires_in_for_ttl() -> None:
    mock_http = MagicMock()
    mock_cache = _empty_cache()
    mock_response = _make_ok_response({"access_token": "t", "token_type": "Bearer", "expires_in": 3600})
    mock_http.post.return_value = mock_response

    with (
        patch("scheduling_modal_with_recurring_support.services.oauth.get_cache", return_value=mock_cache),
        patch("scheduling_modal_with_recurring_support.services.oauth.Http", return_value=mock_http),
    ):
        acquire_token("https://host.canvasmedical.com", "c", "s")

    _key, _data, ttl = mock_cache.set.call_args[0]
    assert ttl == 3600 - EXPIRY_SAFETY_MARGIN_SECONDS


def test_acquire_token_short_expires_in_floored_to_60() -> None:
    mock_http = MagicMock()
    mock_cache = _empty_cache()
    mock_response = _make_ok_response({"access_token": "t", "expires_in": 30})
    mock_http.post.return_value = mock_response

    with (
        patch("scheduling_modal_with_recurring_support.services.oauth.get_cache", return_value=mock_cache),
        patch("scheduling_modal_with_recurring_support.services.oauth.Http", return_value=mock_http),
    ):
        acquire_token("https://host.canvasmedical.com", "c", "s")

    _key, _data, ttl = mock_cache.set.call_args[0]
    assert ttl == 60


def test_acquire_token_missing_expires_in_uses_default_ttl() -> None:
    mock_http = MagicMock()
    mock_cache = _empty_cache()
    mock_response = _make_ok_response({"access_token": "t"})
    mock_http.post.return_value = mock_response

    with (
        patch("scheduling_modal_with_recurring_support.services.oauth.get_cache", return_value=mock_cache),
        patch("scheduling_modal_with_recurring_support.services.oauth.Http", return_value=mock_http),
    ):
        acquire_token("https://host.canvasmedical.com", "c", "s")

    _key, _data, ttl = mock_cache.set.call_args[0]
    assert ttl == DEFAULT_TTL_SECONDS


def test_acquire_token_non_int_expires_in_uses_default_ttl() -> None:
    mock_http = MagicMock()
    mock_cache = _empty_cache()
    mock_response = _make_ok_response({"access_token": "t", "expires_in": "bad-value"})
    mock_http.post.return_value = mock_response

    with (
        patch("scheduling_modal_with_recurring_support.services.oauth.get_cache", return_value=mock_cache),
        patch("scheduling_modal_with_recurring_support.services.oauth.Http", return_value=mock_http),
    ):
        acquire_token("https://host.canvasmedical.com", "c", "s")

    _key, _data, ttl = mock_cache.set.call_args[0]
    assert ttl == DEFAULT_TTL_SECONDS


def test_acquire_token_caches_token_data() -> None:
    mock_http = MagicMock()
    mock_cache = _empty_cache()
    mock_response = _make_ok_response({"access_token": "tok", "token_type": "Bearer"})
    mock_http.post.return_value = mock_response

    with (
        patch("scheduling_modal_with_recurring_support.services.oauth.get_cache", return_value=mock_cache),
        patch("scheduling_modal_with_recurring_support.services.oauth.Http", return_value=mock_http),
    ):
        acquire_token("https://host.canvasmedical.com", "cid", "s")

    key, data, _ttl = mock_cache.set.call_args[0]
    assert "oauth_token::https://host.canvasmedical.com::cid" == key
    assert data == {"access_token": "tok", "token_type": "Bearer"}


def test_token_is_immutable() -> None:
    token = OAuthToken(access_token="t", token_type="Bearer")
    with pytest.raises((AttributeError, TypeError)):
        token.access_token = "changed"  # type: ignore[misc]
