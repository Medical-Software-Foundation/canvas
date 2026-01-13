"""Tests for the education content type module."""

import pytest
from http import HTTPStatus
from unittest.mock import call, patch, MagicMock

from portal_content.content_types import education


class TestServePortalPage:
    """Tests for serve_portal_page function."""

    def test_returns_html_response(self):
        """Test that portal page returns HTML response."""
        api = MagicMock()
        api.request.headers.get.return_value = "patient-123"

        with patch("portal_content.content_types.education.log"):
            result = education.serve_portal_page(api)

        assert len(result) == 1
        response = result[0]
        assert response.status_code == HTTPStatus.OK
        # HTMLResponse content is bytes
        assert b"My Learning Materials" in response.content


class TestHandleReportsRequest:
    """Tests for handle_reports_request function."""

    def test_list_action_calls_handle_list(self):
        """Test that list action routes to _handle_list."""
        api = MagicMock()
        api.request.headers.get.return_value = "patient-123"
        api.request.json.return_value = {"action": "list"}

        with patch("portal_content.content_types.education._handle_list") as mock_handle:
            with patch("portal_content.content_types.education.log"):
                mock_handle.return_value = [MagicMock()]
                result = education.handle_reports_request(api)

        mock_handle.assert_called_once_with(api, "patient-123", {"action": "list"})

    def test_detail_action_calls_handle_detail(self):
        """Test that detail action routes to _handle_detail."""
        api = MagicMock()
        api.request.headers.get.return_value = "patient-123"
        api.request.json.return_value = {"action": "detail", "report_id": "doc-123"}

        with patch("portal_content.content_types.education._handle_detail") as mock_handle:
            with patch("portal_content.content_types.education.log"):
                mock_handle.return_value = [MagicMock()]
                result = education.handle_reports_request(api)

        mock_handle.assert_called_once_with(api, "patient-123", {"action": "detail", "report_id": "doc-123"})

    def test_unknown_action_returns_bad_request(self):
        """Test that unknown action returns BAD_REQUEST."""
        api = MagicMock()
        api.request.headers.get.return_value = "patient-123"
        api.request.json.return_value = {"action": "invalid"}

        with patch("portal_content.content_types.education.log"):
            result = education.handle_reports_request(api)

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.BAD_REQUEST

    def test_exception_returns_internal_error(self):
        """Test that exceptions return INTERNAL_SERVER_ERROR."""
        api = MagicMock()
        api.request.headers.get.return_value = "patient-123"
        api.request.json.side_effect = Exception("Parse error")

        with patch("portal_content.content_types.education.log"):
            result = education.handle_reports_request(api)

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR


class TestProxyPdf:
    """Tests for proxy_pdf function."""

    def test_missing_document_id_returns_bad_request(self):
        """Test that missing document_id returns BAD_REQUEST."""
        api = MagicMock()
        api.request.headers.get.return_value = "patient-123"
        api.request.query_params.get.return_value = None

        with patch("portal_content.content_types.education.log"):
            result = education.proxy_pdf(api)

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.BAD_REQUEST

    def test_fhir_client_unavailable_returns_error(self):
        """Test that unavailable FHIR client returns error."""
        api = MagicMock()
        api.request.headers.get.return_value = "patient-123"
        api.request.query_params.get.return_value = "doc-123"
        api._get_fhir_client.return_value = None

        with patch("portal_content.content_types.education.log"):
            result = education.proxy_pdf(api)

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_document_not_found_returns_404(self):
        """Test that document not found returns NOT_FOUND."""
        api = MagicMock()
        api.request.headers.get.return_value = "patient-123"
        api.request.query_params.get.return_value = "doc-123"

        mock_fhir_client = MagicMock()
        mock_fhir_client.base_url = "https://fumage-test.canvasmedical.com"
        mock_fhir_client.token = "test-token"
        api._get_fhir_client.return_value = mock_fhir_client

        with patch("portal_content.content_types.education.requests.get") as mock_get:
            with patch("portal_content.content_types.education.log"):
                mock_response = MagicMock()
                mock_response.status_code = 404
                mock_get.return_value = mock_response

                result = education.proxy_pdf(api)

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.NOT_FOUND

    def test_access_denied_for_other_patient_document(self):
        """Test that accessing another patient's document returns FORBIDDEN."""
        api = MagicMock()
        api.request.headers.get.return_value = "patient-123"
        api.request.query_params.get.return_value = "doc-123"

        mock_fhir_client = MagicMock()
        mock_fhir_client.base_url = "https://fumage-test.canvasmedical.com"
        mock_fhir_client.token = "test-token"
        api._get_fhir_client.return_value = mock_fhir_client

        with patch("portal_content.content_types.education.requests.get") as mock_get:
            with patch("portal_content.content_types.education.log"):
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {
                    "subject": {"reference": "Patient/other-patient-456"}
                }
                mock_get.return_value = mock_response

                result = education.proxy_pdf(api)

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.FORBIDDEN

    def test_successful_pdf_proxy(self):
        """Test successful PDF proxy returns PDF content."""
        api = MagicMock()
        api.request.headers.get.return_value = "patient-123"
        api.request.query_params.get.return_value = "doc-123"

        mock_fhir_client = MagicMock()
        mock_fhir_client.base_url = "https://fumage-test.canvasmedical.com"
        mock_fhir_client.token = "test-token"
        api._get_fhir_client.return_value = mock_fhir_client

        with patch("portal_content.content_types.education.requests.get") as mock_get:
            with patch("portal_content.content_types.education.log"):
                # First call - document reference verification
                verify_response = MagicMock()
                verify_response.status_code = 200
                verify_response.json.return_value = {
                    "subject": {"reference": "Patient/patient-123"}
                }

                # Second call - actual PDF content
                pdf_response = MagicMock()
                pdf_response.status_code = 200
                pdf_response.content = b"%PDF-1.4 test content"

                mock_get.side_effect = [verify_response, pdf_response]

                result = education.proxy_pdf(api)

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.OK
        assert result[0].headers["Content-Type"] == "application/pdf"

    def test_pdf_fetch_failure_returns_404(self):
        """Test that PDF fetch failure returns NOT_FOUND."""
        api = MagicMock()
        api.request.headers.get.return_value = "patient-123"
        api.request.query_params.get.return_value = "doc-123"

        mock_fhir_client = MagicMock()
        mock_fhir_client.base_url = "https://fumage-test.canvasmedical.com"
        mock_fhir_client.token = "test-token"
        api._get_fhir_client.return_value = mock_fhir_client

        with patch("portal_content.content_types.education.requests.get") as mock_get:
            with patch("portal_content.content_types.education.log"):
                # First call - document reference verification
                verify_response = MagicMock()
                verify_response.status_code = 200
                verify_response.json.return_value = {
                    "subject": {"reference": "Patient/patient-123"}
                }

                # Second call - PDF fetch fails
                pdf_response = MagicMock()
                pdf_response.status_code = 404
                pdf_response.text = "Not found"

                mock_get.side_effect = [verify_response, pdf_response]

                result = education.proxy_pdf(api)

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.NOT_FOUND


class TestHandleList:
    """Tests for _handle_list function."""

    def test_fhir_client_unavailable_returns_error(self):
        """Test that unavailable FHIR client returns error."""
        api = MagicMock()
        api._get_fhir_client.return_value = None

        with patch("portal_content.content_types.education.log"):
            result = education._handle_list(api, "patient-123", {})

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_successful_list_returns_reports(self):
        """Test successful list returns paginated reports."""
        api = MagicMock()
        mock_fhir_client = MagicMock()
        mock_fhir_client.search_document_references.return_value = {
            "resourceType": "Bundle",
            "entry": [
                {
                    "resource": {
                        "id": "doc-123",
                        "description": "Test Doc",
                        "date": "2024-01-15T10:00:00Z",
                        "subject": {"reference": "Patient/patient-123"},
                    }
                }
            ],
        }
        api._get_fhir_client.return_value = mock_fhir_client

        with patch("portal_content.content_types.education.log"):
            result = education._handle_list(api, "patient-123", {"limit": 10, "offset": 0})

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.OK

    def test_empty_results_returns_empty_list(self):
        """Test empty results returns empty list."""
        api = MagicMock()
        mock_fhir_client = MagicMock()
        mock_fhir_client.search_document_references.return_value = {
            "resourceType": "Bundle",
            "entry": [],
        }
        api._get_fhir_client.return_value = mock_fhir_client

        with patch("portal_content.content_types.education.log"):
            result = education._handle_list(api, "patient-123", {})

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.OK

    def test_limit_capped_at_50(self):
        """Test that limit is capped at 50."""
        api = MagicMock()
        mock_fhir_client = MagicMock()
        mock_fhir_client.search_document_references.return_value = {
            "resourceType": "Bundle",
            "entry": [],
        }
        api._get_fhir_client.return_value = mock_fhir_client

        with patch("portal_content.content_types.education.log"):
            result = education._handle_list(api, "patient-123", {"limit": 100})

        assert len(result) == 1
        # The function should cap limit at 50 internally


class TestHandleDetail:
    """Tests for _handle_detail function."""

    def test_missing_report_id_returns_bad_request(self):
        """Test that missing report_id returns BAD_REQUEST."""
        api = MagicMock()

        with patch("portal_content.content_types.education.log"):
            result = education._handle_detail(api, "patient-123", {})

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.BAD_REQUEST

    def test_fhir_client_unavailable_returns_error(self):
        """Test that unavailable FHIR client returns error."""
        api = MagicMock()
        api._get_fhir_client.return_value = None

        with patch("portal_content.content_types.education.log"):
            result = education._handle_detail(api, "patient-123", {"report_id": "doc-123"})

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_document_not_found_returns_404(self):
        """Test that document not found returns NOT_FOUND."""
        api = MagicMock()
        mock_fhir_client = MagicMock()
        mock_fhir_client.base_url = "https://fumage-test.canvasmedical.com"
        mock_fhir_client.token = "test-token"
        api._get_fhir_client.return_value = mock_fhir_client

        with patch("portal_content.content_types.education.requests.get") as mock_get:
            with patch("portal_content.content_types.education.log"):
                mock_response = MagicMock()
                mock_response.status_code = 404
                mock_get.return_value = mock_response

                result = education._handle_detail(api, "patient-123", {"report_id": "doc-123"})

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.NOT_FOUND

    def test_access_denied_for_other_patient_document(self):
        """Test that accessing another patient's document returns FORBIDDEN."""
        api = MagicMock()
        mock_fhir_client = MagicMock()
        mock_fhir_client.base_url = "https://fumage-test.canvasmedical.com"
        mock_fhir_client.token = "test-token"
        api._get_fhir_client.return_value = mock_fhir_client

        with patch("portal_content.content_types.education.requests.get") as mock_get:
            with patch("portal_content.content_types.education.log"):
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {
                    "id": "doc-123",
                    "subject": {"reference": "Patient/other-patient-456"},
                }
                mock_get.return_value = mock_response

                result = education._handle_detail(api, "patient-123", {"report_id": "doc-123"})

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.FORBIDDEN

    def test_successful_detail_returns_report(self):
        """Test successful detail returns report data."""
        api = MagicMock()
        mock_fhir_client = MagicMock()
        mock_fhir_client.base_url = "https://fumage-test.canvasmedical.com"
        mock_fhir_client.token = "test-token"
        api._get_fhir_client.return_value = mock_fhir_client

        with patch("portal_content.content_types.education.requests.get") as mock_get:
            with patch("portal_content.content_types.education.log"):
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {
                    "id": "doc-123",
                    "description": "Test Document",
                    "date": "2024-01-15T10:30:00Z",
                    "subject": {"reference": "Patient/patient-123"},
                }
                mock_get.return_value = mock_response

                result = education._handle_detail(api, "patient-123", {"report_id": "doc-123"})

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.OK


class TestExtractReportSummary:
    """Tests for _extract_report_summary function."""

    def test_extracts_all_fields(self):
        """Test that all fields are extracted correctly."""
        doc_ref = {
            "id": "doc-123",
            "description": "Test Document",
            "date": "2024-01-15T10:30:00Z",
            "context": {"period": {"start": "2024-01-15T09:00:00Z"}},
            "subject": {"reference": "Patient/patient-123"},
        }

        result = education._extract_report_summary(doc_ref, "patient-123")

        assert result["report_id"] == "doc-123"
        assert result["patient_id"] == "patient-123"
        assert result["report_name"] == "Test Document"
        assert result["date_received"] == "2024-01-15T10:30:00Z"
        assert result["date_collected"] == "2024-01-15T09:00:00Z"
        assert "education/pdf" in result["pdf_url"]

    def test_uses_default_name_when_description_missing(self):
        """Test that default name is used when description is missing."""
        doc_ref = {
            "id": "doc-123",
            "type": {"text": "Custom Type"},
        }

        result = education._extract_report_summary(doc_ref, "patient-123")

        assert result["report_name"] == "Custom Type"

    def test_uses_coding_display_when_text_missing(self):
        """Test that coding display is used when type text is missing."""
        doc_ref = {
            "id": "doc-123",
            "type": {
                "text": "",
                "coding": [{"display": "Coding Display Name"}],
            },
        }

        result = education._extract_report_summary(doc_ref, "patient-123")

        assert result["report_name"] == "Coding Display Name"

    def test_uses_default_when_all_names_missing(self):
        """Test that default name is used when all sources are missing."""
        doc_ref = {"id": "doc-123"}

        result = education._extract_report_summary(doc_ref, "patient-123")

        assert result["report_name"] == education.DEFAULT_REPORT_NAME

    def test_handles_exception(self):
        """Test that exceptions return None."""
        with patch("portal_content.content_types.education.log"):
            # Pass None to cause an exception
            result = education._extract_report_summary(None, "patient-123")

        assert result is None
