"""Tests for OAuth 2.0 client-credentials token acquisition and caching."""
import pytest
from unittest.mock import MagicMock, call, patch


class TestGetAccessToken:
    def test_fetches_token_when_cache_miss(self, full_secrets):
        mock_cache = MagicMock()
        mock_cache.get.return_value = None

        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {"access_token": "tok-abc", "expires_in": 3600}

        mock_http = MagicMock()
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.oauth.get_cache", return_value=mock_cache),
            patch("cms_access_fhir_client.oauth.Http", return_value=mock_http),
        ):
            from cms_access_fhir_client.oauth import get_access_token
            token = get_access_token(full_secrets)

        assert token == "tok-abc"
        assert mock_cache.mock_calls == [
            call.get("access_oauth_token_test-client-id"),
            call.set("access_oauth_token_test-client-id", "tok-abc", timeout_seconds=3540),
        ]
        # http.post() is called; response.json() is then called on the return value,
        # which shows up as call.post().json() in mock_http.mock_calls
        assert mock_http.mock_calls == [
            call.post(
                "https://auth.cms.gov/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": "test-client-id",
                    "client_secret": "test-client-secret",
                },
            ),
            call.post().json(),
        ]

    def test_returns_cached_token_without_http(self, full_secrets):
        mock_cache = MagicMock()
        mock_cache.get.return_value = "cached-token"

        mock_http = MagicMock()

        with (
            patch("cms_access_fhir_client.oauth.get_cache", return_value=mock_cache),
            patch("cms_access_fhir_client.oauth.Http", return_value=mock_http),
        ):
            from cms_access_fhir_client.oauth import get_access_token
            token = get_access_token(full_secrets)

        assert token == "cached-token"
        assert mock_cache.mock_calls == [call.get("access_oauth_token_test-client-id")]
        assert mock_http.mock_calls == []

    def test_ttl_is_expires_in_minus_60(self, full_secrets):
        mock_cache = MagicMock()
        mock_cache.get.return_value = None

        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {"access_token": "tok", "expires_in": 1800}

        mock_http = MagicMock()
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.oauth.get_cache", return_value=mock_cache),
            patch("cms_access_fhir_client.oauth.Http", return_value=mock_http),
        ):
            from cms_access_fhir_client.oauth import get_access_token
            get_access_token(full_secrets)

        # TTL should be 1800 - 60 = 1740
        set_call = mock_cache.mock_calls[1]
        assert set_call == call.set(
            "access_oauth_token_test-client-id", "tok", timeout_seconds=1740
        )

    def test_ttl_minimum_is_60_seconds(self, full_secrets):
        mock_cache = MagicMock()
        mock_cache.get.return_value = None

        mock_response = MagicMock()
        mock_response.ok = True
        # expires_in = 30 → max(30-60, 60) = 60
        mock_response.json.return_value = {"access_token": "tok", "expires_in": 30}

        mock_http = MagicMock()
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.oauth.get_cache", return_value=mock_cache),
            patch("cms_access_fhir_client.oauth.Http", return_value=mock_http),
        ):
            from cms_access_fhir_client.oauth import get_access_token
            get_access_token(full_secrets)

        set_call = mock_cache.mock_calls[1]
        assert set_call == call.set(
            "access_oauth_token_test-client-id", "tok", timeout_seconds=60
        )

    def test_raises_if_client_id_missing(self):
        from cms_access_fhir_client.oauth import get_access_token
        with pytest.raises(ValueError, match="ACCESS_OAUTH_CLIENT_ID"):
            get_access_token({})

    def test_raises_if_client_secret_missing(self):
        from cms_access_fhir_client.oauth import get_access_token
        with pytest.raises(ValueError, match="ACCESS_OAUTH_CLIENT_SECRET"):
            get_access_token({"ACCESS_OAUTH_CLIENT_ID": "id"})

    def test_raises_if_token_url_missing(self):
        from cms_access_fhir_client.oauth import get_access_token
        with pytest.raises(ValueError, match="ACCESS_OAUTH_TOKEN_URL"):
            get_access_token(
                {"ACCESS_OAUTH_CLIENT_ID": "id", "ACCESS_OAUTH_CLIENT_SECRET": "secret"}
            )

    def test_raises_runtime_error_on_http_failure(self, full_secrets):
        mock_cache = MagicMock()
        mock_cache.get.return_value = None

        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"

        mock_http = MagicMock()
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.oauth.get_cache", return_value=mock_cache),
            patch("cms_access_fhir_client.oauth.Http", return_value=mock_http),
        ):
            from cms_access_fhir_client.oauth import get_access_token
            with pytest.raises(RuntimeError, match="OAuth token request failed"):
                get_access_token(full_secrets)

        assert mock_cache.mock_calls == [call.get("access_oauth_token_test-client-id")]
        # ok/status_code/text are plain values on the mock, so attribute access is not recorded;
        # the RuntimeError raise is already verified by the pytest.raises context manager above

    def test_raises_when_access_token_missing_from_response(self, full_secrets):
        """Response 200 OK but body lacks access_token field."""
        mock_cache = MagicMock()
        mock_cache.get.return_value = None

        mock_response = MagicMock()
        mock_response.ok = True
        # Missing access_token key
        mock_response.json.return_value = {"token_type": "Bearer"}

        mock_http = MagicMock()
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.oauth.get_cache", return_value=mock_cache),
            patch("cms_access_fhir_client.oauth.Http", return_value=mock_http),
        ):
            from cms_access_fhir_client.oauth import get_access_token
            with pytest.raises(RuntimeError, match="missing access_token"):
                get_access_token(full_secrets)
