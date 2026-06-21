"""Tests for OAuth 2.0 client-credentials token acquisition and caching.

The Operations Manual v0.9.11 documents form-field credentials; a prior cycle found
the live server accepting only HTTP Basic. The client tries the documented form-field
method first and falls back to Basic on a 401. ``ACCESS_OAUTH_AUTH_STYLE`` can pin a
single style.
"""
import base64
import pytest
from unittest.mock import MagicMock, call, patch


def _ok_response(token="tok", expires_in=300):
    resp = MagicMock()
    resp.ok = True
    resp.status_code = 200
    resp.json.return_value = {"access_token": token, "expires_in": expires_in}
    return resp


def _401_response():
    resp = MagicMock()
    resp.ok = False
    resp.status_code = 401
    resp.text = "Unauthorized"
    return resp


class TestGetAccessToken:
    def test_default_uses_basic_auth(self, full_secrets):
        """Default 'auto' style sends HTTP Basic first (confirmed correct for CMS IDM/Okta)."""
        mock_cache = MagicMock()
        mock_cache.get.return_value = None
        mock_http = MagicMock()
        mock_http.post.return_value = _ok_response("tok-abc")

        with (
            patch("cms_access_fhir_client.oauth.get_cache", return_value=mock_cache),
            patch("cms_access_fhir_client.oauth.Http", return_value=mock_http),
        ):
            from cms_access_fhir_client.oauth import get_access_token
            token = get_access_token(full_secrets)

        assert token == "tok-abc"
        post_call = mock_http.post.call_args
        assert post_call[0][0] == "https://auth.cms.gov/token"
        # Basic auth header, credentials NOT in the form body
        expected = "Basic " + base64.b64encode(b"test-client-id:test-client-secret").decode()
        assert post_call[1]["headers"]["Authorization"] == expected
        form_data = post_call[1]["data"]
        assert form_data["grant_type"] == "client_credentials"
        assert "scope" in form_data
        assert "client_id" not in form_data
        assert "client_secret" not in form_data

    def test_falls_back_to_form_field_on_401(self, full_secrets):
        """When the Basic attempt returns 401, the client retries with form-field creds."""
        mock_cache = MagicMock()
        mock_cache.get.return_value = None
        mock_http = MagicMock()
        # First attempt (basic) → 401, second attempt (post) → success
        mock_http.post.side_effect = [_401_response(), _ok_response("tok-post")]

        with (
            patch("cms_access_fhir_client.oauth.get_cache", return_value=mock_cache),
            patch("cms_access_fhir_client.oauth.Http", return_value=mock_http),
        ):
            from cms_access_fhir_client.oauth import get_access_token
            token = get_access_token(full_secrets)

        assert token == "tok-post"
        assert mock_http.post.call_count == 2
        # Second (form-field) call carried credentials in the body, no Basic header
        second = mock_http.post.call_args_list[1][1]
        assert second["data"]["client_id"] == "test-client-id"
        assert second["data"]["client_secret"] == "test-client-secret"
        assert "Authorization" not in second["headers"]

    def test_auth_style_basic_pins_basic_only(self, full_secrets):
        """ACCESS_OAUTH_AUTH_STYLE=basic skips the form-field attempt entirely."""
        secrets = {**full_secrets, "ACCESS_OAUTH_AUTH_STYLE": "basic"}
        mock_cache = MagicMock()
        mock_cache.get.return_value = None
        mock_http = MagicMock()
        mock_http.post.return_value = _ok_response("tok")

        with (
            patch("cms_access_fhir_client.oauth.get_cache", return_value=mock_cache),
            patch("cms_access_fhir_client.oauth.Http", return_value=mock_http),
        ):
            from cms_access_fhir_client.oauth import get_access_token
            get_access_token(secrets)

        assert mock_http.post.call_count == 1
        headers = mock_http.post.call_args[1]["headers"]
        assert headers["Authorization"].startswith("Basic ")
        # Basic style keeps credentials out of the form body
        form_data = mock_http.post.call_args[1]["data"]
        assert "client_id" not in form_data

    def test_uses_default_scope_when_not_in_secrets(self, full_secrets):
        secrets = {k: v for k, v in full_secrets.items() if k != "ACCESS_OAUTH_SCOPE"}
        mock_cache = MagicMock()
        mock_cache.get.return_value = None
        mock_http = MagicMock()
        mock_http.post.return_value = _ok_response()

        with (
            patch("cms_access_fhir_client.oauth.get_cache", return_value=mock_cache),
            patch("cms_access_fhir_client.oauth.Http", return_value=mock_http),
        ):
            from cms_access_fhir_client.oauth import get_access_token
            get_access_token(secrets)

        assert mock_http.post.call_args[1]["data"]["scope"] == "cdx/*.read cdx/fhir-resource.write"

    def test_uses_custom_scope_from_secrets(self, full_secrets):
        secrets = {**full_secrets, "ACCESS_OAUTH_SCOPE": "cdx/*.read"}
        mock_cache = MagicMock()
        mock_cache.get.return_value = None
        mock_http = MagicMock()
        mock_http.post.return_value = _ok_response()

        with (
            patch("cms_access_fhir_client.oauth.get_cache", return_value=mock_cache),
            patch("cms_access_fhir_client.oauth.Http", return_value=mock_http),
        ):
            from cms_access_fhir_client.oauth import get_access_token
            get_access_token(secrets)

        assert mock_http.post.call_args[1]["data"]["scope"] == "cdx/*.read"

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

    def test_ttl_is_expires_in_minus_120(self, full_secrets):
        mock_cache = MagicMock()
        mock_cache.get.return_value = None
        mock_http = MagicMock()
        mock_http.post.return_value = _ok_response("tok", expires_in=1800)

        with (
            patch("cms_access_fhir_client.oauth.get_cache", return_value=mock_cache),
            patch("cms_access_fhir_client.oauth.Http", return_value=mock_http),
        ):
            from cms_access_fhir_client.oauth import get_access_token
            get_access_token(full_secrets)

        set_call = mock_cache.mock_calls[1]
        assert set_call == call.set(
            "access_oauth_token_test-client-id", "tok", timeout_seconds=1680
        )

    def test_ttl_minimum_is_30_seconds(self, full_secrets):
        mock_cache = MagicMock()
        mock_cache.get.return_value = None
        mock_http = MagicMock()
        # expires_in = 60 → max(60-120, 30) = 30
        mock_http.post.return_value = _ok_response("tok", expires_in=60)

        with (
            patch("cms_access_fhir_client.oauth.get_cache", return_value=mock_cache),
            patch("cms_access_fhir_client.oauth.Http", return_value=mock_http),
        ):
            from cms_access_fhir_client.oauth import get_access_token
            get_access_token(full_secrets)

        set_call = mock_cache.mock_calls[1]
        assert set_call == call.set(
            "access_oauth_token_test-client-id", "tok", timeout_seconds=30
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

    def test_raises_runtime_error_when_all_styles_fail(self, full_secrets):
        """Both form-field and Basic attempts return 401 → RuntimeError, nothing cached."""
        mock_cache = MagicMock()
        mock_cache.get.return_value = None
        mock_http = MagicMock()
        mock_http.post.return_value = _401_response()

        with (
            patch("cms_access_fhir_client.oauth.get_cache", return_value=mock_cache),
            patch("cms_access_fhir_client.oauth.Http", return_value=mock_http),
        ):
            from cms_access_fhir_client.oauth import get_access_token
            with pytest.raises(RuntimeError, match="OAuth token request failed"):
                get_access_token(full_secrets)

        assert mock_cache.mock_calls == [call.get("access_oauth_token_test-client-id")]

    def test_raises_when_access_token_missing_from_response(self, full_secrets):
        mock_cache = MagicMock()
        mock_cache.get.return_value = None
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 200
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
