"""Tests for practitioner_bulk_loader.utils.fhir_client."""

from unittest.mock import MagicMock, patch

import pytest

from practitioner_bulk_loader.utils.fhir_client import (
    FhirClient,
    create_practitioner,
    get_location_map,
    make_fhir_client,
    read_practitioner,
    replace_practitioner,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(base_url: str = "https://fumage-test.canvasmedical.com") -> FhirClient:
    """Return a FhirClient with a dummy token for unit-test use."""
    return FhirClient(base_url=base_url, access_token="test-access-token")


# ---------------------------------------------------------------------------
# FhirClient unit tests
# ---------------------------------------------------------------------------

class TestFhirClient:
    def test_auth_headers_contain_bearer(self):
        client = _make_client()
        headers = client._auth_headers()
        assert headers["Authorization"] == "Bearer test-access-token"
        assert headers["Content-Type"] == "application/json"

    def test_get_calls_http_get(self):
        client = _make_client()
        mock_response = MagicMock()
        mock_response.json.return_value = {"resourceType": "Bundle", "entry": []}
        mock_response.raise_for_status.return_value = None

        with patch.object(client._http, "get", return_value=mock_response) as mock_get:
            result = client.get("/Practitioner", params={"telecom": "a@b.com"})

        mock_get.assert_called_once()
        called_url = mock_get.call_args[0][0]
        assert "Practitioner" in called_url
        assert "telecom" in called_url
        assert result == {"resourceType": "Bundle", "entry": []}

    def test_post_calls_http_post_and_returns_response(self):
        client = _make_client()
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.headers = {"Location": "/Practitioner/new-uuid"}

        with patch.object(client._http, "post", return_value=mock_response) as mock_post:
            result = client.post("/Practitioner", json_body={"resourceType": "Practitioner"})

        mock_post.assert_called_once()
        assert result is mock_response

    def test_put_calls_http_put_with_json_body(self):
        """PUT is used for full-resource replacement (e.g. adding a license
        to an existing Practitioner) — Canvas Fumage rejects PATCH."""
        client = _make_client()
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None

        with patch.object(client._http, "put", return_value=mock_response) as mock_put:
            client.put(
                "/Practitioner/uuid",
                json_body={"resourceType": "Practitioner"},
            )

        call_kwargs = mock_put.call_args[1]
        assert "Authorization" in call_kwargs["headers"]
        assert call_kwargs["json"] == {"resourceType": "Practitioner"}


# ---------------------------------------------------------------------------
# make_fhir_client
# ---------------------------------------------------------------------------

class TestMakeFhirClient:
    def _mock_http(self, token: str = "tok123"):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"access_token": token, "expires_in": 3600}
        mock_http = MagicMock()
        mock_http.post.return_value = mock_response
        return mock_http

    def test_returns_fhir_client_with_fumage_base_url(self):
        secrets = {"fumage-client-id": "client-id", "fumage-client-secret": "client-secret"}
        environment = {"CUSTOMER_IDENTIFIER": "myinstance"}

        with patch("practitioner_bulk_loader.utils.fhir_client.Http") as mock_http_cls:
            mock_http_cls.return_value = self._mock_http()
            client = make_fhir_client(secrets, environment)

        assert isinstance(client, FhirClient)
        assert client.base_url == "https://fumage-myinstance.canvasmedical.com"
        assert client.access_token == "tok123"

    def test_auth_host_is_non_fumage_canvas_host(self):
        secrets = {"fumage-client-id": "cid", "fumage-client-secret": "csec"}
        environment = {"CUSTOMER_IDENTIFIER": "acmecorp"}

        with patch("practitioner_bulk_loader.utils.fhir_client.Http") as mock_http_cls:
            mock_http_cls.return_value = self._mock_http(token="tok")
            make_fhir_client(secrets, environment)

        base_arg = mock_http_cls.call_args_list[0][0][0]
        assert base_arg == "https://acmecorp.canvasmedical.com"

    def test_posts_client_credentials_grant(self):
        secrets = {"fumage-client-id": "my-client-id", "fumage-client-secret": "my-client-secret"}
        environment = {"CUSTOMER_IDENTIFIER": "test"}

        with patch("practitioner_bulk_loader.utils.fhir_client.Http") as mock_http_cls:
            mock_http = self._mock_http(token="t")
            mock_http_cls.return_value = mock_http
            make_fhir_client(secrets, environment)

        post_kwargs = mock_http.post.call_args[1]
        assert "client_credentials" in post_kwargs["data"]
        assert "my-client-id" in post_kwargs["data"]
        assert "my-client-secret" in post_kwargs["data"]

    def test_missing_client_id_raises(self):
        from practitioner_bulk_loader.utils.fhir_client import MissingSecretError
        with pytest.raises(MissingSecretError, match="fumage-client-id"):
            make_fhir_client(
                {"fumage-client-id": "", "fumage-client-secret": "x"},
                {"CUSTOMER_IDENTIFIER": "test"},
            )

    def test_missing_customer_identifier_raises(self):
        from practitioner_bulk_loader.utils.fhir_client import MissingSecretError
        with pytest.raises(MissingSecretError, match="CUSTOMER_IDENTIFIER"):
            make_fhir_client(
                {"fumage-client-id": "x", "fumage-client-secret": "y"},
                {"CUSTOMER_IDENTIFIER": ""},
            )


# ---------------------------------------------------------------------------
# read_practitioner
# ---------------------------------------------------------------------------

class TestReadPractitioner:
    def test_reads_by_uuid_stripping_prefix(self):
        client = _make_client()
        client.get = MagicMock(return_value={"id": "prac-uuid", "resourceType": "Practitioner"})

        result = read_practitioner(client, "Practitioner/prac-uuid")

        assert result["id"] == "prac-uuid"
        client.get.assert_called_once_with("/Practitioner/prac-uuid")

    def test_works_without_prefix(self):
        client = _make_client()
        client.get = MagicMock(return_value={"id": "plain-uuid"})

        read_practitioner(client, "plain-uuid")

        client.get.assert_called_once_with("/Practitioner/plain-uuid")


# ---------------------------------------------------------------------------
# create_practitioner
# ---------------------------------------------------------------------------

class TestCreatePractitioner:
    def test_returns_practitioner_id_from_location_header(self):
        client = _make_client()
        mock_response = MagicMock()
        mock_response.headers = {"Location": "/Practitioner/new-uuid-456"}
        client.post = MagicMock(return_value=mock_response)

        result = create_practitioner(client, {"resourceType": "Practitioner"})

        assert result == "Practitioner/new-uuid-456"
        client.post.assert_called_once_with("/Practitioner", json_body={"resourceType": "Practitioner"})

    def test_returns_empty_string_when_no_location_header(self):
        client = _make_client()
        mock_response = MagicMock()
        mock_response.headers = {}
        client.post = MagicMock(return_value=mock_response)

        result = create_practitioner(client, {})

        assert result == ""

    def test_parses_last_segment_of_location_header(self):
        client = _make_client()
        mock_response = MagicMock()
        # Location header with trailing slash
        mock_response.headers = {"Location": "/Practitioner/abc-def-ghi/"}
        client.post = MagicMock(return_value=mock_response)

        result = create_practitioner(client, {})

        assert result == "Practitioner/abc-def-ghi"


# ---------------------------------------------------------------------------
# replace_practitioner — PUT used because Canvas Fumage rejects PATCH
# ---------------------------------------------------------------------------

class TestReplacePractitioner:
    def test_puts_full_resource_to_practitioner_path(self):
        client = _make_client()
        client.put = MagicMock()

        resource = {"resourceType": "Practitioner", "id": "existing-xyz", "qualification": []}
        replace_practitioner(client, "Practitioner/existing-xyz", resource)

        call_args = client.put.call_args
        assert call_args[0][0] == "/Practitioner/existing-xyz"
        assert call_args[1]["json_body"] == resource

    def test_strips_practitioner_prefix_from_id(self):
        client = _make_client()
        client.put = MagicMock()

        replace_practitioner(client, "Practitioner/clean-id", {"resourceType": "Practitioner"})

        called_path = client.put.call_args[0][0]
        assert called_path == "/Practitioner/clean-id"
        assert "Practitioner/Practitioner" not in called_path

    def test_accepts_bare_uuid(self):
        client = _make_client()
        client.put = MagicMock()

        replace_practitioner(client, "bare-uuid-123", {"resourceType": "Practitioner"})

        called_path = client.put.call_args[0][0]
        assert called_path == "/Practitioner/bare-uuid-123"


# ---------------------------------------------------------------------------
# get_location_map
# ---------------------------------------------------------------------------

class TestGetLocationMap:
    def test_returns_name_to_reference_map(self):
        client = _make_client()
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "entry": [
                {"resource": {"id": "loc-abc", "name": "Main Clinic"}},
                {"resource": {"id": "loc-def", "name": "West Clinic"}},
            ],
            "link": [],
        }

        with patch.object(client, "_http") as mock_http:
            mock_http.get.return_value = mock_response
            result = get_location_map(client)

        assert result["main clinic"] == "Location/loc-abc"
        assert result["west clinic"] == "Location/loc-def"

    def test_empty_bundle_returns_empty_map(self):
        client = _make_client()
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"entry": [], "link": []}

        with patch.object(client, "_http") as mock_http:
            mock_http.get.return_value = mock_response
            result = get_location_map(client)

        assert result == {}

    def test_name_key_is_lowercased(self):
        client = _make_client()
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "entry": [
                {"resource": {"id": "loc-xyz", "name": "UPPER CASE CLINIC"}},
            ],
            "link": [],
        }

        with patch.object(client, "_http") as mock_http:
            mock_http.get.return_value = mock_response
            result = get_location_map(client)

        assert "upper case clinic" in result
        assert result["upper case clinic"] == "Location/loc-xyz"

    def test_paginates_via_next_link(self):
        client = _make_client()

        page1 = MagicMock()
        page1.raise_for_status.return_value = None
        page1.json.return_value = {
            "entry": [{"resource": {"id": "loc-1", "name": "Clinic A"}}],
            "link": [{"relation": "next", "url": "https://fumage-test.canvasmedical.com/Location?page=2"}],
        }

        page2 = MagicMock()
        page2.raise_for_status.return_value = None
        page2.json.return_value = {
            "entry": [{"resource": {"id": "loc-2", "name": "Clinic B"}}],
            "link": [],
        }

        with patch.object(client, "_http") as mock_http:
            mock_http.get.side_effect = [page1, page2]
            result = get_location_map(client)

        assert "clinic a" in result
        assert "clinic b" in result
        assert mock_http.get.call_count == 2

