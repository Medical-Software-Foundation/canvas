"""Tests for CMS ACCESS FHIR API client functions.

Covers:
- URL path structure: /access/Patient/$<op>
- entityId query param on every operation POST
- participantID body field name (not "participant")
- Prefer: respond-async header
- poll_submission_status returns (status_code, body) tuple
- OperationOutcome parsing on 400 pre-validation failures
"""
import pytest
from unittest.mock import MagicMock, patch


SECRETS = {
    "ACCESS_BASE_URL": "https://api.access.cms.gov/fhir",
    "ACCESS_PARTICIPANT_ID": "ACCES10098",
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

    def test_sets_prefer_respond_async_header(self):
        """_build_http must inject Prefer: respond-async on every call."""
        from cms_access_fhir_client.cms_client import _build_http

        mock_http_instance = MagicMock()
        mock_http_instance.headers = {}

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http_instance),
        ):
            http, _ = _build_http(SECRETS)

        assert http.headers.get("Prefer") == "respond-async"


_PATIENT_RESOURCE = {
    "resourceType": "Patient",
    "identifier": [
        {"system": "http://hl7.org/fhir/sid/us-mbi", "value": "1EG4-TE5-MK72"}
    ],
    "name": [{"family": "Doe", "given": ["Jane"]}],
    "birthDate": "1942-06-15",
}


class TestCheckEligibility:
    def test_raises_when_participant_id_missing(self):
        from cms_access_fhir_client.cms_client import check_eligibility
        with pytest.raises(ValueError, match="ACCESS_PARTICIPANT_ID"):
            check_eligibility({}, patient_resource=_PATIENT_RESOURCE)

    def test_posts_to_access_prefix_path(self):
        """Path must be /access/Patient/$check-eligibility (not /Patient/$check-eligibility)."""
        from cms_access_fhir_client.cms_client import check_eligibility

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"parameter": []}
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            check_eligibility(SECRETS, patient_resource=_PATIENT_RESOURCE)

        path = mock_http.post.call_args[0][0]
        assert path == "/access/Patient/$check-eligibility"

    def test_sends_entity_id_as_query_param(self):
        """entityId must be sent as a query param, not only in the body."""
        from cms_access_fhir_client.cms_client import check_eligibility

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"parameter": []}
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            check_eligibility(SECRETS, patient_resource=_PATIENT_RESOURCE)

        kwargs = mock_http.post.call_args[1]
        assert kwargs.get("params", {}).get("entityId") == "ACCES10098"

    def test_body_uses_participantID_field_name(self):
        """Body parameter must be 'participantID' (camelCase, capital-ID), not 'participant'."""
        from cms_access_fhir_client.cms_client import check_eligibility

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"parameter": []}
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            check_eligibility(SECRETS, patient_resource=_PATIENT_RESOURCE)

        payload = mock_http.post.call_args[1]["json"]
        param_names = [p["name"] for p in payload["parameter"]]
        assert "participantID" in param_names
        assert "participant" not in param_names

    def test_patient_parameter_uses_resource_key_not_value_reference(self):
        """Patient param must use 'resource' (inline) not 'valueReference' (external reference)."""
        from cms_access_fhir_client.cms_client import check_eligibility

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"parameter": []}
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            check_eligibility(SECRETS, patient_resource=_PATIENT_RESOURCE)

        payload = mock_http.post.call_args[1]["json"]
        patient_param = next(p for p in payload["parameter"] if p["name"] == "patient")
        assert "resource" in patient_param
        assert "valueReference" not in patient_param

    def test_patient_resource_contains_mbi_identifier(self):
        """Patient resource in the body must include the us-mbi identifier."""
        from cms_access_fhir_client.cms_client import check_eligibility

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"parameter": []}
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            check_eligibility(SECRETS, patient_resource=_PATIENT_RESOURCE)

        payload = mock_http.post.call_args[1]["json"]
        patient_param = next(p for p in payload["parameter"] if p["name"] == "patient")
        resource = patient_param["resource"]
        assert resource["resourceType"] == "Patient"
        identifiers = resource["identifier"]
        assert any(
            i["system"] == "http://hl7.org/fhir/sid/us-mbi" and i["value"] == "1EG4-TE5-MK72"
            for i in identifiers
        )

    def test_patient_resource_contains_name_and_birth_date(self):
        """Patient resource must include name and birthDate fields."""
        from cms_access_fhir_client.cms_client import check_eligibility

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"parameter": []}
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            check_eligibility(SECRETS, patient_resource=_PATIENT_RESOURCE)

        payload = mock_http.post.call_args[1]["json"]
        patient_param = next(p for p in payload["parameter"] if p["name"] == "patient")
        resource = patient_param["resource"]
        assert resource["name"][0]["family"] == "Doe"
        assert resource["birthDate"] == "1942-06-15"

    def test_raises_runtime_error_on_400_with_operation_outcome(self):
        """400 + OperationOutcome must raise RuntimeError with the detail text."""
        from cms_access_fhir_client.cms_client import check_eligibility

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "resourceType": "OperationOutcome",
            "issue": [
                {
                    "severity": "error",
                    "code": "invalid",
                    "details": {"text": "participantID not found in registry"},
                }
            ],
        }
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            with pytest.raises(RuntimeError, match="participantID not found in registry"):
                check_eligibility(SECRETS, patient_resource=_PATIENT_RESOURCE)

    def test_raises_runtime_error_on_400_with_no_issues(self):
        """400 + OperationOutcome with empty issues list falls back to 'Unknown error'."""
        from cms_access_fhir_client.cms_client import check_eligibility

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "resourceType": "OperationOutcome",
            "issue": [],
        }
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            with pytest.raises(RuntimeError, match="Unknown error"):
                check_eligibility(SECRETS, patient_resource=_PATIENT_RESOURCE)


class TestAlign:
    def test_raises_when_participant_id_missing(self):
        from cms_access_fhir_client.cms_client import align
        with pytest.raises(ValueError, match="ACCESS_PARTICIPANT_ID"):
            align({}, patient_resource=_PATIENT_RESOURCE, track="eCKM", clinical_justification="Justified")

    def test_posts_to_access_prefix_path(self):
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
            align(SECRETS, patient_resource=_PATIENT_RESOURCE, track="eCKM", clinical_justification="CKD")

        path = mock_http.post.call_args[0][0]
        assert path == "/access/Patient/$align"

    def test_sends_entity_id_as_query_param(self):
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
            align(SECRETS, patient_resource=_PATIENT_RESOURCE, track="eCKM", clinical_justification="CKD")

        kwargs = mock_http.post.call_args[1]
        assert kwargs.get("params", {}).get("entityId") == "ACCES10098"

    def test_body_uses_participantID_field_name(self):
        from cms_access_fhir_client.cms_client import align

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.headers.get.return_value = None
        mock_response.text = ""
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            align(SECRETS, patient_resource=_PATIENT_RESOURCE, track="MSK", clinical_justification="Arthritis")

        payload = mock_http.post.call_args[1]["json"]
        param_names = [p["name"] for p in payload["parameter"]]
        assert "participantID" in param_names
        assert "participant" not in param_names

    def test_patient_parameter_uses_resource_key_not_value_reference(self):
        """align patient param must use 'resource' (inline) not 'valueReference'."""
        from cms_access_fhir_client.cms_client import align

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.headers.get.return_value = None
        mock_response.text = ""
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            align(SECRETS, patient_resource=_PATIENT_RESOURCE, track="eCKM", clinical_justification="CKD")

        payload = mock_http.post.call_args[1]["json"]
        patient_param = next(p for p in payload["parameter"] if p["name"] == "patient")
        assert "resource" in patient_param
        assert "valueReference" not in patient_param

    def test_patient_resource_contains_mbi_identifier(self):
        """align patient resource must include the us-mbi identifier."""
        from cms_access_fhir_client.cms_client import align

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.headers.get.return_value = None
        mock_response.text = ""
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            align(SECRETS, patient_resource=_PATIENT_RESOURCE, track="eCKM", clinical_justification="CKD")

        payload = mock_http.post.call_args[1]["json"]
        patient_param = next(p for p in payload["parameter"] if p["name"] == "patient")
        resource = patient_param["resource"]
        assert any(
            i["system"] == "http://hl7.org/fhir/sid/us-mbi"
            for i in resource["identifier"]
        )

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
                patient_resource=_PATIENT_RESOURCE,
                track="eCKM",
                clinical_justification="CKD stage 3",
            )

        assert status_code == 202
        assert content_location == "https://api.cms.gov/status/abc"
        assert body == {}

    def test_raises_on_400_operation_outcome(self):
        from cms_access_fhir_client.cms_client import align

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "resourceType": "OperationOutcome",
            "issue": [{"severity": "error", "code": "invalid", "details": {"text": "Invalid track"}}],
        }
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            with pytest.raises(RuntimeError, match="Invalid track"):
                align(SECRETS, patient_resource=_PATIENT_RESOURCE, track="INVALID", clinical_justification="x")


class TestUnalign:
    def test_raises_when_participant_id_missing(self):
        from cms_access_fhir_client.cms_client import unalign
        with pytest.raises(ValueError, match="ACCESS_PARTICIPANT_ID"):
            unalign({}, alignment_id="align-1", reason_code="patient-request")

    def test_posts_to_access_prefix_path(self):
        from cms_access_fhir_client.cms_client import unalign

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.headers.get.return_value = "https://api.cms.gov/status/xyz"
        mock_response.text = ""
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            unalign(SECRETS, alignment_id="align-1", reason_code="care-completed")

        path = mock_http.post.call_args[0][0]
        assert path == "/access/Patient/$unalign"

    def test_sends_entity_id_as_query_param(self):
        from cms_access_fhir_client.cms_client import unalign

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.headers.get.return_value = None
        mock_response.text = ""
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            unalign(SECRETS, alignment_id="align-1", reason_code="care-completed")

        kwargs = mock_http.post.call_args[1]
        assert kwargs.get("params", {}).get("entityId") == "ACCES10098"

    def test_body_uses_participantID_field_name(self):
        from cms_access_fhir_client.cms_client import unalign

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.headers.get.return_value = None
        mock_response.text = ""
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            unalign(SECRETS, alignment_id="align-1", reason_code="care-completed")

        payload = mock_http.post.call_args[1]["json"]
        param_names = [p["name"] for p in payload["parameter"]]
        assert "participantID" in param_names
        assert "participant" not in param_names

    def test_body_does_not_contain_patient_parameter(self):
        """$unalign does not send a patient parameter — alignment_id identifies the record."""
        from cms_access_fhir_client.cms_client import unalign

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.headers.get.return_value = None
        mock_response.text = ""
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            unalign(SECRETS, alignment_id="align-1", reason_code="care-completed")

        payload = mock_http.post.call_args[1]["json"]
        param_names = [p["name"] for p in payload["parameter"]]
        assert "patient" not in param_names

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
                alignment_id="align-abc",
                reason_code="provider-decision",
            )

        assert status_code == 202
        assert content_location == "https://api.cms.gov/status/unalign-xyz"
        assert body == {}

    def test_raises_on_400_operation_outcome(self):
        from cms_access_fhir_client.cms_client import unalign

        mock_http = _mock_http_and_token()
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "resourceType": "OperationOutcome",
            "issue": [{"severity": "error", "code": "invalid", "details": {"text": "Alignment not found"}}],
        }
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            with pytest.raises(RuntimeError, match="Alignment not found"):
                unalign(SECRETS, alignment_id="align-1", reason_code="other")


class TestReportData:
    def test_raises_not_implemented(self):
        from cms_access_fhir_client.cms_client import report_data
        with pytest.raises(NotImplementedError):
            report_data(SECRETS, patient_fhir_id="p-123", alignment_id="align-1")


class TestPollSubmissionStatus:
    def test_returns_status_code_and_body_tuple(self):
        """poll_submission_status returns (status_code, body) — not just body."""
        from cms_access_fhir_client.cms_client import poll_submission_status

        mock_http = MagicMock()
        mock_http.headers = {}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"resourceType": "Parameters"}'
        mock_response.json.return_value = {"resourceType": "Parameters", "parameter": []}
        mock_http.get.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            result = poll_submission_status(SECRETS, "https://api.cms.gov/status/abc")

        assert isinstance(result, tuple)
        status_code, body = result
        assert status_code == 200
        assert body["resourceType"] == "Parameters"

    def test_returns_202_with_empty_body_for_in_progress(self):
        """202 response (in-progress) must return (202, {}) without raising."""
        from cms_access_fhir_client.cms_client import poll_submission_status

        mock_http = MagicMock()
        mock_http.headers = {}
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.text = ""
        mock_http.get.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            status_code, body = poll_submission_status(SECRETS, "https://api.cms.gov/status/abc")

        assert status_code == 202
        assert body == {}
        # raise_for_status must NOT have been called on 202
        mock_response.raise_for_status.assert_not_called()

    def test_does_not_raise_on_202(self):
        """Explicit: 202 must not trigger raise_for_status."""
        from cms_access_fhir_client.cms_client import poll_submission_status

        mock_http = MagicMock()
        mock_http.headers = {}
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.text = ""
        mock_http.get.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            # Should not raise
            poll_submission_status(SECRETS, "https://api.cms.gov/status/abc")

        mock_response.raise_for_status.assert_not_called()

    def test_gets_status_url_with_bearer_token(self):
        from cms_access_fhir_client.cms_client import poll_submission_status

        mock_http = MagicMock()
        mock_http.headers = {}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"resourceType": "Parameters"}'
        mock_response.json.return_value = {"resourceType": "Parameters"}
        mock_http.get.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            poll_submission_status(SECRETS, "https://api.cms.gov/status/abc")

        assert mock_http.get.call_args[0][0] == "https://api.cms.gov/status/abc"
        assert "Bearer tok" in mock_http.headers.get("Authorization", "")


class TestParseOperationOutcome:
    def test_extracts_detail_text(self):
        from cms_access_fhir_client.cms_client import _parse_operation_outcome
        body = {
            "resourceType": "OperationOutcome",
            "issue": [{"severity": "error", "code": "invalid", "details": {"text": "Bad ID"}}],
        }
        assert _parse_operation_outcome(body) == "Bad ID"

    def test_returns_unknown_error_for_empty_issues(self):
        from cms_access_fhir_client.cms_client import _parse_operation_outcome
        assert _parse_operation_outcome({"issue": []}) == "Unknown error"
        assert _parse_operation_outcome({}) == "Unknown error"
