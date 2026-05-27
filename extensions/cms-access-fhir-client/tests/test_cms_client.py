"""Tests for CMS ACCESS FHIR API client functions.

Covers:
- URL path structure: /access/Patient/$<op>
- entityId query param on every operation POST
- Flat parameter shape: participantID, payerID, track, mbi at top level (no nested Patient resource)
- Prefer: respond-async header on all operations
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

_MBI = "1EG4-TE5-MK72"
_PAYER_ID = "payer-001"
_TRACK = "eCKM"


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

    def test_returns_headers_with_bearer_token(self):
        from cms_access_fhir_client.cms_client import _build_http

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok-123"),
            patch("cms_access_fhir_client.cms_client.Http") as mock_http_cls,
        ):
            http, headers = _build_http(SECRETS)

        assert headers.get("Authorization") == "Bearer tok-123"
        # base URL must be normalized to end with a slash so urljoin keeps the prefix
        mock_http_cls.assert_called_once_with(base_url="https://api.access.cms.gov/fhir/")

    def test_sets_prefer_respond_async_header(self):
        """_build_http must inject Prefer: respond-async on every call."""
        from cms_access_fhir_client.cms_client import _build_http

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http"),
        ):
            _, headers = _build_http(SECRETS)

        assert headers.get("Prefer") == "respond-async"


class TestCheckEligibility:
    def test_raises_when_participant_id_missing(self):
        from cms_access_fhir_client.cms_client import check_eligibility
        with pytest.raises(ValueError, match="ACCESS_PARTICIPANT_ID"):
            check_eligibility({}, mbi=_MBI, payer_id=_PAYER_ID, track=_TRACK)

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
            check_eligibility(SECRETS, mbi=_MBI, payer_id=_PAYER_ID, track=_TRACK)

        path = mock_http.post.call_args[0][0]
        assert path == "access/Patient/$check-eligibility?entityId=ACCES10098"

    def test_sends_entity_id_as_query_param(self):
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
            check_eligibility(SECRETS, mbi=_MBI, payer_id=_PAYER_ID, track=_TRACK)

        path = mock_http.post.call_args[0][0]
        assert "entityId=ACCES10098" in path

    def test_flat_payload_has_all_four_required_params(self):
        """Payload must have participantID, payerID, track, mbi as top-level parameters.
        No nested Patient resource — CMS resolves the patient by MBI on their side."""
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
            check_eligibility(SECRETS, mbi=_MBI, payer_id=_PAYER_ID, track=_TRACK)

        payload = mock_http.post.call_args[1]["json"]
        param_names = [p["name"] for p in payload["parameter"]]
        assert "participantID" in param_names
        assert "payerID" in param_names
        assert "track" in param_names
        assert "mbi" in param_names

    def test_no_nested_patient_resource(self):
        """CMS rejected embedded Patient resource — must not be present."""
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
            check_eligibility(SECRETS, mbi=_MBI, payer_id=_PAYER_ID, track=_TRACK)

        payload = mock_http.post.call_args[1]["json"]
        param_names = [p["name"] for p in payload["parameter"]]
        assert "patient" not in param_names

    def test_payer_id_value_forwarded(self):
        """payerID parameter must carry the payer_id argument value."""
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
            check_eligibility(SECRETS, mbi=_MBI, payer_id="payer-XYZ", track=_TRACK)

        payload = mock_http.post.call_args[1]["json"]
        payer_param = next(p for p in payload["parameter"] if p["name"] == "payerID")
        assert payer_param["valueString"] == "payer-XYZ"

    def test_mbi_value_forwarded(self):
        """mbi parameter must carry the mbi argument value."""
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
            check_eligibility(SECRETS, mbi="TESTMBI99", payer_id=_PAYER_ID, track=_TRACK)

        payload = mock_http.post.call_args[1]["json"]
        mbi_param = next(p for p in payload["parameter"] if p["name"] == "mbi")
        assert mbi_param["valueString"] == "TESTMBI99"

    def test_track_value_forwarded(self):
        """track parameter must use valueCode."""
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
            check_eligibility(SECRETS, mbi=_MBI, payer_id=_PAYER_ID, track="MSK")

        payload = mock_http.post.call_args[1]["json"]
        track_param = next(p for p in payload["parameter"] if p["name"] == "track")
        assert track_param["valueCode"] == "MSK"

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
                check_eligibility(SECRETS, mbi=_MBI, payer_id=_PAYER_ID, track=_TRACK)

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
                check_eligibility(SECRETS, mbi=_MBI, payer_id=_PAYER_ID, track=_TRACK)

    def test_error_message_matches_cms_real_error(self):
        """Regression: the exact CMS error from the live test cycle must propagate."""
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
                    "details": {
                        "text": "Payload validation failed with the following error: "
                                "missing required field(s): participantID, payerID, track, mbi"
                    },
                }
            ],
        }
        mock_http.post.return_value = mock_response

        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            with pytest.raises(RuntimeError, match="missing required field"):
                check_eligibility(SECRETS, mbi=_MBI, payer_id=_PAYER_ID, track=_TRACK)


class TestAlign:
    def test_raises_when_participant_id_missing(self):
        from cms_access_fhir_client.cms_client import align
        with pytest.raises(ValueError, match="ACCESS_PARTICIPANT_ID"):
            align({}, mbi=_MBI, payer_id=_PAYER_ID, track=_TRACK, clinical_justification="CKD")

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
            align(SECRETS, mbi=_MBI, payer_id=_PAYER_ID, track=_TRACK, clinical_justification="CKD")

        path = mock_http.post.call_args[0][0]
        assert path == "access/Patient/$align?entityId=ACCES10098"

    def test_flat_payload_has_all_required_params(self):
        """Align payload must include participantID, payerID, track, mbi, clinicalJustification."""
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
            align(SECRETS, mbi=_MBI, payer_id=_PAYER_ID, track="MSK", clinical_justification="Arthritis")

        payload = mock_http.post.call_args[1]["json"]
        param_names = [p["name"] for p in payload["parameter"]]
        assert "participantID" in param_names
        assert "payerID" in param_names
        assert "track" in param_names
        assert "mbi" in param_names
        assert "clinicalJustification" in param_names

    def test_no_nested_patient_resource(self):
        """align must not send a nested Patient resource."""
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
            align(SECRETS, mbi=_MBI, payer_id=_PAYER_ID, track=_TRACK, clinical_justification="CKD")

        payload = mock_http.post.call_args[1]["json"]
        param_names = [p["name"] for p in payload["parameter"]]
        assert "patient" not in param_names

    def test_payer_id_and_mbi_values_forwarded(self):
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
            align(SECRETS, mbi="MBI-TEST", payer_id="PAYER-TEST", track=_TRACK, clinical_justification="CKD")

        payload = mock_http.post.call_args[1]["json"]
        by_name = {p["name"]: p for p in payload["parameter"]}
        assert by_name["mbi"]["valueString"] == "MBI-TEST"
        assert by_name["payerID"]["valueString"] == "PAYER-TEST"

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
                mbi=_MBI,
                payer_id=_PAYER_ID,
                track=_TRACK,
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
                align(SECRETS, mbi=_MBI, payer_id=_PAYER_ID, track="INVALID", clinical_justification="x")


class TestUnalign:
    def test_raises_when_participant_id_missing(self):
        from cms_access_fhir_client.cms_client import unalign
        with pytest.raises(ValueError, match="ACCESS_PARTICIPANT_ID"):
            unalign({}, mbi=_MBI, payer_id=_PAYER_ID, track=_TRACK, alignment_id="align-1", reason_code="patient-request")

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
            unalign(SECRETS, mbi=_MBI, payer_id=_PAYER_ID, track=_TRACK, alignment_id="align-1", reason_code="care-completed")

        path = mock_http.post.call_args[0][0]
        assert path == "access/Patient/$unalign?entityId=ACCES10098"

    def test_flat_payload_has_all_required_params(self):
        """Unalign payload must include participantID, payerID, track, mbi, alignmentId, reasonCode."""
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
            unalign(SECRETS, mbi=_MBI, payer_id=_PAYER_ID, track=_TRACK, alignment_id="align-1", reason_code="care-completed")

        payload = mock_http.post.call_args[1]["json"]
        param_names = [p["name"] for p in payload["parameter"]]
        assert "participantID" in param_names
        assert "payerID" in param_names
        assert "track" in param_names
        assert "mbi" in param_names
        assert "alignmentId" in param_names
        assert "reasonCode" in param_names

    def test_no_nested_patient_resource(self):
        """$unalign must not send a nested Patient resource."""
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
            unalign(SECRETS, mbi=_MBI, payer_id=_PAYER_ID, track=_TRACK, alignment_id="align-1", reason_code="care-completed")

        payload = mock_http.post.call_args[1]["json"]
        param_names = [p["name"] for p in payload["parameter"]]
        assert "patient" not in param_names

    def test_track_pulled_from_alignment_record(self):
        """track is sourced from the existing alignment record, not the HTTP request."""
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
            unalign(SECRETS, mbi=_MBI, payer_id=_PAYER_ID, track="BH", alignment_id="align-1", reason_code="care-completed")

        payload = mock_http.post.call_args[1]["json"]
        by_name = {p["name"]: p for p in payload["parameter"]}
        assert by_name["track"]["valueCode"] == "BH"

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
                mbi=_MBI,
                payer_id=_PAYER_ID,
                track=_TRACK,
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
                unalign(SECRETS, mbi=_MBI, payer_id=_PAYER_ID, track=_TRACK, alignment_id="align-1", reason_code="other")


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
        headers = mock_http.get.call_args[1].get("headers", {})
        assert headers.get("Authorization") == "Bearer tok"


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
