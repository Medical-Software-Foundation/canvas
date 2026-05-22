"""Tests for OAuth 2.0 client-credentials token acquisition and caching.

CMS ACCESS requires HTTP Basic auth: credentials are sent as
``Authorization: Basic base64(client_id:client_secret)`` and the form body
must contain only ``grant_type`` and ``scope``.  Sending client_id/client_secret
as form fields is rejected.
"""
import base64
import pytest
from unittest.mock import MagicMock, call, patch


def _make_basic_header(client_id: str, client_secret: str) -> str:
    raw = f"{client_id}:{client_secret}".encode()
    return "Basic " + base64.b64encode(raw).decode()


class TestGetAccessToken:
    def test_fetches_token_with_basic_auth_header(self, full_secrets):
        """OAuth POST must include Authorization: Basic ... header, NOT form fields."""
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

        post_call = mock_http.post.call_args
        # First positional arg is the URL
        assert post_call[0][0] == "https://auth.cms.gov/token"

        # Form body: grant_type + scope only — NO client_id or client_secret
        form_data = post_call[1]["data"]
        assert form_data["grant_type"] == "client_credentials"
        assert "scope" in form_data
        assert "client_id" not in form_data
        assert "client_secret" not in form_data

        # Authorization header must be Basic with correct base64
        headers = post_call[1]["headers"]
        expected_header = _make_basic_header("test-client-id", "test-client-secret")
        assert headers["Authorization"] == expected_header

    def test_basic_auth_header_is_correct_base64(self, full_secrets):
        """The encoded header must decode back to 'client_id:client_secret'."""
        mock_cache = MagicMock()
        mock_cache.get.return_value = None

        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {"access_token": "tok", "expires_in": 300}

        mock_http = MagicMock()
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.oauth.get_cache", return_value=mock_cache),
            patch("cms_access_fhir_client.oauth.Http", return_value=mock_http),
        ):
            from cms_access_fhir_client.oauth import get_access_token
            get_access_token(full_secrets)

        headers = mock_http.post.call_args[1]["headers"]
        auth = headers["Authorization"]
        assert auth.startswith("Basic ")
        decoded = base64.b64decode(auth[len("Basic "):]).decode()
        assert decoded == "test-client-id:test-client-secret"

    def test_uses_default_scope_when_not_in_secrets(self, full_secrets):
        """Scope defaults to 'cdx/*.read cdx/fhir-resource.write' when not set."""
        secrets = {k: v for k, v in full_secrets.items() if k != "ACCESS_OAUTH_SCOPE"}
        mock_cache = MagicMock()
        mock_cache.get.return_value = None

        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {"access_token": "tok", "expires_in": 300}

        mock_http = MagicMock()
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.oauth.get_cache", return_value=mock_cache),
            patch("cms_access_fhir_client.oauth.Http", return_value=mock_http),
        ):
            from cms_access_fhir_client.oauth import get_access_token
            get_access_token(secrets)

        form_data = mock_http.post.call_args[1]["data"]
        assert form_data["scope"] == "cdx/*.read cdx/fhir-resource.write"

    def test_uses_custom_scope_from_secrets(self, full_secrets):
        """ACCESS_OAUTH_SCOPE secret overrides the default scope."""
        secrets = {**full_secrets, "ACCESS_OAUTH_SCOPE": "cdx/*.read"}
        mock_cache = MagicMock()
        mock_cache.get.return_value = None

        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {"access_token": "tok", "expires_in": 300}

        mock_http = MagicMock()
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.oauth.get_cache", return_value=mock_cache),
            patch("cms_access_fhir_client.oauth.Http", return_value=mock_http),
        ):
            from cms_access_fhir_client.oauth import get_access_token
            get_access_token(secrets)

        form_data = mock_http.post.call_args[1]["data"]
        assert form_data["scope"] == "cdx/*.read"

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
