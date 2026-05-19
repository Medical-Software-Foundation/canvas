"""Tests for CMS ACCESS FHIR API client functions."""
import pytest
from unittest.mock import MagicMock, call, patch


SECRETS = {
    "ACCESS_BASE_URL": "https://api.access.cms.gov/fhir",
    "ACCESS_PARTICIPANT_ID": "part-001",
    "ACCESS_OAUTH_CLIENT_ID": "client-id",
    "ACCESS_OAUTH_CLIENT_SECRET": "client-secret",
    "ACCESS_OAUTH_TOKEN_URL": "https://auth.cms.gov/token",
}


def _mock_http_and_token():
    mock_http = MagicMock()
    mock_http.headers = {}
    return mock_http


class TestBuildHttp:
    def test_raises_when_base_url_missing(self):
        from cms_access_fhir_client.cms_client import _build_http
        with pytest.raises(ValueError, match="ACCESS_BASE_URL"):
            _build_http({})

    def test_fails_closed_if_token_fails(self):
        from cms_access_fhir_client.cms_client import _build_http
        with patch(
            "cms_access_fhir_client.cms_client.get_access_token",
            side_effect=ValueError("Missing secret"),
        ):
            with pytest.raises(ValueError):
                _build_http(SECRETS)

    def test_returns_http_with_auth_header(self):
        from cms_access_fhir_client.cms_client import _build_http

        mock_http_instance = MagicMock()
        mock_http_instance.headers = {}

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok-123"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http_instance),
        ):
            http, base_url = _build_http(SECRETS)

        assert base_url == "https://api.access.cms.gov/fhir"
        assert "Bearer tok-123" in http.headers.get("Authorization", "")


class TestCheckEligibility:
    def test_raises_when_participant_id_missing(self):
        from cms_access_fhir_client.cms_client import check_eligibility
        with pytest.raises(ValueError, match="ACCESS_PARTICIPANT_ID"):
            check_eligibility({}, patient_fhir_id="p-123")

    def test_posts_to_check_eligibility_endpoint(self):
        from cms_access_fhir_client.cms_client import check_eligibility

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.json.return_value = {"parameter": []}
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            result = check_eligibility(SECRETS, patient_fhir_id="patient-fhir-123")

        assert result == {"parameter": []}
        assert mock_http.post.call_args[0][0] == "/Patient/$check-eligibility"
        payload = mock_http.post.call_args[1]["json"]
        assert payload["resourceType"] == "Parameters"
        patient_param = next(p for p in payload["parameter"] if p["name"] == "patient")
        assert "Patient/patient-fhir-123" in patient_param["valueReference"]["reference"]


class TestAlign:
    def test_raises_when_participant_id_missing(self):
        from cms_access_fhir_client.cms_client import align
        with pytest.raises(ValueError, match="ACCESS_PARTICIPANT_ID"):
            align({}, patient_fhir_id="p-123", track="eCKM", clinical_justification="Justified")

    def test_returns_202_with_content_location(self):
        from cms_access_fhir_client.cms_client import align

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.headers.get.return_value = "https://api.cms.gov/status/abc"
        mock_response.text = ""
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            status_code, content_location, body = align(
                SECRETS,
                patient_fhir_id="p-fhir-123",
                track="eCKM",
                clinical_justification="CKD stage 3",
            )

        assert status_code == 202
        assert content_location == "https://api.cms.gov/status/abc"
        assert body == {}

    def test_posts_to_align_endpoint(self):
        from cms_access_fhir_client.cms_client import align

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers.get.return_value = None
        mock_response.text = '{"status": "ok"}'
        mock_response.json.return_value = {"status": "ok"}
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            align(SECRETS, patient_fhir_id="p-123", track="MSK", clinical_justification="Arthritis")

        assert mock_http.post.call_args[0][0] == "/Patient/$align"
        payload = mock_http.post.call_args[1]["json"]
        track_param = next(p for p in payload["parameter"] if p["name"] == "track")
        assert track_param["valueCode"] == "MSK"


class TestUnalign:
    def test_raises_when_participant_id_missing(self):
        from cms_access_fhir_client.cms_client import unalign
        with pytest.raises(ValueError, match="ACCESS_PARTICIPANT_ID"):
            unalign({}, patient_fhir_id="p-123", alignment_id="align-1", reason_code="patient-request")

    def test_returns_status_and_location(self):
        from cms_access_fhir_client.cms_client import unalign

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.headers.get.return_value = "https://api.cms.gov/status/unalign-xyz"
        mock_response.text = ""
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            status_code, content_location, body = unalign(
                SECRETS,
                patient_fhir_id="p-fhir-123",
                alignment_id="align-abc",
                reason_code="provider-decision",
            )

        assert status_code == 202
        assert content_location == "https://api.cms.gov/status/unalign-xyz"
        assert body == {}

    def test_posts_to_unalign_endpoint(self):
        from cms_access_fhir_client.cms_client import unalign

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers.get.return_value = None
        mock_response.text = ""
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            unalign(SECRETS, patient_fhir_id="p-123", alignment_id="align-1", reason_code="care-completed")

        assert mock_http.post.call_args[0][0] == "/Patient/$unalign"
        payload = mock_http.post.call_args[1]["json"]
        reason_param = next(p for p in payload["parameter"] if p["name"] == "reasonCode")
        assert reason_param["valueCode"] == "care-completed"


class TestReportData:
    def test_raises_not_implemented(self):
        from cms_access_fhir_client.cms_client import report_data
        with pytest.raises(NotImplementedError):
            report_data(SECRETS, patient_fhir_id="p-123", alignment_id="align-1")


class TestPollSubmissionStatus:
    def test_gets_status_url(self):
        from cms_access_fhir_client.cms_client import poll_submission_status

        mock_http = MagicMock()
        mock_http.headers = {}
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "in-progress"}
        mock_http.get.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            result = poll_submission_status(SECRETS, "https://api.cms.gov/status/abc")

        assert result == {"status": "in-progress"}
        assert mock_http.get.call_args[0][0] == "https://api.cms.gov/status/abc"
        assert "Bearer tok" in mock_http.headers.get("Authorization", "")
