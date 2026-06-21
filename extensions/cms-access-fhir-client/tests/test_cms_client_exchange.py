"""Tests for the request/response exchange capture (debug=) added for the inspector UI."""
import pytest
from unittest.mock import MagicMock, patch

SECRETS = {
    "ACCESS_BASE_URL": "https://api.access.cms.gov/fhir",
    "ACCESS_PARTICIPANT_ID": "ACCES12345",
}

_PATIENT_RESOURCE = {"resourceType": "Patient", "id": "p-1"}
_PAYER_ID = "00831"
_TRACK = "eCKM"


def _mock_response(status_code=202, headers=None, text="", json_body=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 300
    resp.headers = headers or {}
    resp.text = text
    resp.json.return_value = json_body if json_body is not None else {}
    return resp


class TestRedactHeaders:
    def test_masks_bearer_token(self):
        from cms_access_fhir_client.cms_client import _redact_headers

        out = _redact_headers({"Authorization": "Bearer supersecrettoken", "Prefer": "respond-async"})
        assert "supersecrettoken" not in out["Authorization"]
        assert out["Authorization"].startswith("Bearer <redacted")
        assert out["Prefer"] == "respond-async"


class TestCheckEligibilityExchange:
    def test_captures_full_exchange_on_success(self):
        from cms_access_fhir_client.cms_client import check_eligibility

        resp = _mock_response(
            status_code=202,
            headers={"Content-Location": "https://cms.test/submission-status/sub-1"},
        )
        mock_http = MagicMock()
        mock_http.post.return_value = resp
        debug: list = []
        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok-abc"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            status, content_location, _ = check_eligibility(
                SECRETS,
                patient_resource=_PATIENT_RESOURCE,
                payer_id=_PAYER_ID,
                track=_TRACK,
                debug=debug,
            )

        assert status == 202
        assert content_location == "https://cms.test/submission-status/sub-1"
        assert len(debug) == 1
        exch = debug[0]
        # Request side
        assert exch["request"]["method"] == "POST"
        assert "access/Patient/$check-eligibility" in exch["request"]["url"]
        assert exch["request"]["query_params"] == {"entityId": "ACCES12345"}
        assert exch["request"]["body"]["resourceType"] == "Parameters"
        assert "tok-abc" not in exch["request"]["headers"]["Authorization"]
        # Response side
        assert exch["response"]["status_code"] == 202
        assert exch["response"]["content_location"] == "https://cms.test/submission-status/sub-1"

    def test_captures_exchange_even_when_cms_returns_400(self):
        from cms_access_fhir_client.cms_client import check_eligibility

        oo = {"resourceType": "OperationOutcome", "issue": [{"details": {"text": "Missing patient"}}]}
        resp = _mock_response(status_code=400, text="{...}", json_body=oo)
        mock_http = MagicMock()
        mock_http.post.return_value = resp
        debug: list = []
        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            with pytest.raises(RuntimeError, match="Missing patient"):
                check_eligibility(
                    SECRETS,
                    patient_resource=_PATIENT_RESOURCE,
                    payer_id=_PAYER_ID,
                    track=_TRACK,
                    debug=debug,
                )

        # The error body must be captured for troubleshooting, despite the raise.
        assert len(debug) == 1
        assert debug[0]["response"]["status_code"] == 400
        assert debug[0]["response"]["body"]["resourceType"] == "OperationOutcome"

    def test_no_debug_list_means_no_capture(self):
        from cms_access_fhir_client.cms_client import check_eligibility

        resp = _mock_response(status_code=202, headers={"Content-Location": "x"})
        mock_http = MagicMock()
        mock_http.post.return_value = resp
        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            # Should not raise even though debug is omitted (default None).
            status, _, _ = check_eligibility(
                SECRETS, patient_resource=_PATIENT_RESOURCE, payer_id=_PAYER_ID, track=_TRACK
            )
        assert status == 202


class TestPollExchange:
    def test_poll_captures_get_exchange(self):
        from cms_access_fhir_client.cms_client import poll_submission_status

        body = {"resourceType": "Parameters", "parameter": []}
        resp = _mock_response(status_code=200, text="{...}", json_body=body)
        mock_http = MagicMock()
        mock_http.get.return_value = resp
        debug: list = []
        with (
            patch("cms_access_fhir_client.cms_client.get_access_token", return_value="tok"),
            patch("cms_access_fhir_client.cms_client.Http", return_value=mock_http),
        ):
            status, out = poll_submission_status(
                SECRETS, "https://cms.test/submission-status/sub-1", debug=debug
            )
        assert status == 200
        assert len(debug) == 1
        assert debug[0]["request"]["method"] == "GET"
        assert debug[0]["request"]["url"] == "https://cms.test/submission-status/sub-1"
        assert debug[0]["response"]["body"]["resourceType"] == "Parameters"
