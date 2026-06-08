"""Tests for the Photon GraphQL client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from photon_integration.client.photon_client import PhotonClient, PhotonError

CLIENT_MODULE = "photon_integration.client.photon_client"


def _response(status_code=200, json_body=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body if json_body is not None else {}
    resp.text = text
    return resp


def _make_client(env="sandbox"):
    """Build a client whose Http and token are mocked for GraphQL tests."""
    with patch(f"{CLIENT_MODULE}.Http") as http_cls:
        http = http_cls.return_value
        client = PhotonClient("cid", "secret", env=env)
    # Bypass auth/caching for GraphQL-level tests.
    client._get_token = MagicMock(return_value="tok")  # type: ignore[method-assign]
    return client, http


class TestInit:
    def test_requires_credentials(self):
        with pytest.raises(PhotonError):
            PhotonClient("", "secret")
        with pytest.raises(PhotonError):
            PhotonClient("cid", "")

    def test_sandbox_urls(self):
        client, _ = _make_client("sandbox")
        assert client.graphql_url == "https://api.neutron.health/graphql"
        assert client.auth_url == "https://auth.neutron.health/oauth/token"

    def test_production_urls(self):
        client, _ = _make_client("production")
        assert client.graphql_url == "https://api.photon.health/graphql"

    def test_unknown_env_defaults_to_sandbox(self):
        client, _ = _make_client("staging")
        assert client.env == "sandbox"


class TestAuth:
    def test_fetch_token_success(self):
        with patch(f"{CLIENT_MODULE}.Http") as http_cls:
            http = http_cls.return_value
            http.post.return_value = _response(json_body={"access_token": "abc"})
            client = PhotonClient("cid", "secret")
            assert client._fetch_token() == "abc"
        payload = http.post.call_args.kwargs["json"]
        assert payload["grant_type"] == "client_credentials"
        assert payload["audience"] == "https://api.neutron.health"

    def test_fetch_token_http_error(self):
        with patch(f"{CLIENT_MODULE}.Http") as http_cls:
            http_cls.return_value.post.return_value = _response(status_code=401, text="nope")
            client = PhotonClient("cid", "secret")
            with pytest.raises(PhotonError, match="auth failed"):
                client._fetch_token()

    def test_fetch_token_missing_token(self):
        with patch(f"{CLIENT_MODULE}.Http") as http_cls:
            http_cls.return_value.post.return_value = _response(json_body={})
            client = PhotonClient("cid", "secret")
            with pytest.raises(PhotonError, match="access_token"):
                client._fetch_token()

    def test_get_token_uses_cache(self):
        with patch(f"{CLIENT_MODULE}.Http"), patch(f"{CLIENT_MODULE}.get_cache") as gc:
            gc.return_value.get_or_set.return_value = "cached-token"
            client = PhotonClient("cid", "secret")
            assert client._get_token() == "cached-token"
        gc.return_value.get_or_set.assert_called_once()
        args = gc.return_value.get_or_set.call_args.args
        assert args[0] == "photon_token_sandbox"


class TestGraphQL:
    def test_graphql_success(self):
        client, http = _make_client()
        http.post.return_value = _response(json_body={"data": {"ok": 1}})
        assert client._graphql("query", {}) == {"ok": 1}
        headers = http.post.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer tok"

    def test_graphql_http_error(self):
        client, http = _make_client()
        http.post.return_value = _response(status_code=500, text="boom")
        with pytest.raises(PhotonError, match="HTTP 500"):
            client._graphql("q", {})

    def test_graphql_errors_field(self):
        client, http = _make_client()
        http.post.return_value = _response(json_body={"errors": [{"message": "bad"}]})
        with pytest.raises(PhotonError, match="GraphQL error"):
            client._graphql("q", {})

    def test_graphql_no_data(self):
        client, http = _make_client()
        http.post.return_value = _response(json_body={})
        with pytest.raises(PhotonError, match="no data"):
            client._graphql("q", {})


class TestPatients:
    def test_create_patient_returns_id(self):
        client, http = _make_client()
        http.post.return_value = _response(json_body={"data": {"createPatient": {"id": "pat_2"}}})
        assert client.create_patient({"externalId": "ext"}) == "pat_2"

    def test_create_patient_no_id_raises(self):
        client, http = _make_client()
        http.post.return_value = _response(json_body={"data": {"createPatient": None}})
        with pytest.raises(PhotonError, match="createPatient"):
            client.create_patient({})


class TestTreatments:
    def test_find_treatment_returns_id(self):
        client, http = _make_client()
        http.post.return_value = _response(
            json_body={"data": {"medications": [{"id": "med_1", "name": "Lisinopril"}]}}
        )
        assert client.find_treatment_id("lisinopril") == "med_1"
        # searches the medications catalog by drug name
        variables = http.post.call_args.kwargs["json"]["variables"]
        assert variables["filter"] == {"drug": {"name": "lisinopril"}}

    def test_find_treatment_no_match(self):
        client, http = _make_client()
        http.post.return_value = _response(json_body={"data": {"medications": []}})
        assert client.find_treatment_id("zzz") is None

    def test_find_treatment_empty_term(self):
        client, http = _make_client()
        assert client.find_treatment_id("") is None
        http.post.assert_not_called()


