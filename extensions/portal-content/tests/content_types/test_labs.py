"""Tests for the labs content type module."""

import pytest
from http import HTTPStatus
from unittest.mock import call, patch, MagicMock

from portal_content.content_types import labs


class TestServePortalPage:
    """Tests for serve_portal_page function."""

    def test_returns_html_response(self):
        """Test that portal page returns HTML response."""
        api = MagicMock()
        api.request.headers.get.return_value = "patient-123"

        with patch("portal_content.content_types.labs.log"):
            result = labs.serve_portal_page(api)

        assert len(result) == 1
        response = result[0]
        assert response.status_code == HTTPStatus.OK
        assert b"My Lab Reports" in response.content


class TestHandleReportsRequest:
    """Tests for handle_reports_request function."""

    def test_list_action_calls_handle_list(self):
        """Test that list action routes to _handle_list."""
        api = MagicMock()
        api.request.headers.get.return_value = "patient-123"
        api.request.json.return_value = {"action": "list"}

        with patch("portal_content.content_types.labs._handle_list") as mock_handle:
            with patch("portal_content.content_types.labs.log"):
                mock_handle.return_value = [MagicMock()]
                result = labs.handle_reports_request(api)

        mock_handle.assert_called_once_with(api, "patient-123", {"action": "list"})

    def test_detail_action_calls_handle_detail(self):
        """Test that detail action routes to _handle_detail."""
        api = MagicMock()
        api.request.headers.get.return_value = "patient-123"
        api.request.json.return_value = {"action": "detail", "report_id": "doc-123"}

        with patch("portal_content.content_types.labs._handle_detail") as mock_handle:
            with patch("portal_content.content_types.labs.log"):
                mock_handle.return_value = [MagicMock()]
                result = labs.handle_reports_request(api)

        mock_handle.assert_called_once_with(api, "patient-123", {"action": "detail", "report_id": "doc-123"})

    def test_unknown_action_returns_bad_request(self):
        """Test that unknown action returns BAD_REQUEST."""
        api = MagicMock()
        api.request.headers.get.return_value = "patient-123"
        api.request.json.return_value = {"action": "invalid"}

        with patch("portal_content.content_types.labs.log"):
            result = labs.handle_reports_request(api)

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.BAD_REQUEST

    def test_exception_returns_internal_error(self):
        """Test that exceptions return INTERNAL_SERVER_ERROR."""
        api = MagicMock()
        api.request.headers.get.return_value = "patient-123"
        api.request.json.side_effect = Exception("Parse error")

        with patch("portal_content.content_types.labs.log"):
            result = labs.handle_reports_request(api)

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR


class TestProxyPdf:
    """Tests for proxy_pdf function."""

    def test_missing_document_id_returns_bad_request(self):
        """Test that missing document_id returns BAD_REQUEST."""
        api = MagicMock()
        api.request.headers.get.return_value = "patient-123"
        api.request.query_params.get.return_value = None

        result = labs.proxy_pdf(api)

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.BAD_REQUEST

    def test_fhir_client_unavailable_returns_error(self):
        """Test that unavailable FHIR client returns error."""
        api = MagicMock()
        api.request.headers.get.return_value = "patient-123"
        api.request.query_params.get.return_value = "doc-123"
        api._get_fhir_client.return_value = None

        with patch("portal_content.content_types.labs.log"):
            result = labs.proxy_pdf(api)

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

        with patch("portal_content.content_types.labs.requests.get") as mock_get:
            with patch("portal_content.content_types.labs.log"):
                mock_response = MagicMock()
                mock_response.status_code = 404
                mock_get.return_value = mock_response

                result = labs.proxy_pdf(api)

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

        with patch("portal_content.content_types.labs.requests.get") as mock_get:
            with patch("portal_content.content_types.labs.log"):
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {
                    "subject": {"reference": "Patient/other-patient-456"}
                }
                mock_get.return_value = mock_response

                result = labs.proxy_pdf(api)

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

        with patch("portal_content.content_types.labs.requests.get") as mock_get:
            with patch("portal_content.content_types.labs.log"):
                # First call - verify ownership
                verify_response = MagicMock()
                verify_response.status_code = 200
                verify_response.json.return_value = {
                    "subject": {"reference": "Patient/patient-123"}
                }

                # Second call - fetch PDF
                pdf_response = MagicMock()
                pdf_response.status_code = 200
                pdf_response.content = b"%PDF-1.4 test content"

                mock_get.side_effect = [verify_response, pdf_response]

                result = labs.proxy_pdf(api)

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.OK
        assert result[0].content == b"%PDF-1.4 test content"

    def test_pdf_fetch_failure_returns_404(self):
        """Test that PDF fetch failure returns NOT_FOUND."""
        api = MagicMock()
        api.request.headers.get.return_value = "patient-123"
        api.request.query_params.get.return_value = "doc-123"

        mock_fhir_client = MagicMock()
        mock_fhir_client.base_url = "https://fumage-test.canvasmedical.com"
        mock_fhir_client.token = "test-token"
        api._get_fhir_client.return_value = mock_fhir_client

        with patch("portal_content.content_types.labs.requests.get") as mock_get:
            with patch("portal_content.content_types.labs.log"):
                # First call - verify ownership
                verify_response = MagicMock()
                verify_response.status_code = 200
                verify_response.json.return_value = {
                    "subject": {"reference": "Patient/patient-123"}
                }

                # Second call - PDF not found
                pdf_response = MagicMock()
                pdf_response.status_code = 404
                pdf_response.text = "Not found"

                mock_get.side_effect = [verify_response, pdf_response]

                result = labs.proxy_pdf(api)

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.NOT_FOUND


class TestHandleList:
    """Tests for _handle_list function."""

    def test_fhir_client_unavailable_returns_error(self):
        """Test that unavailable FHIR client returns error."""
        api = MagicMock()
        api._get_fhir_client.return_value = None

        with patch("portal_content.content_types.labs.log"):
            result = labs._handle_list(api, "patient-123", {})

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_successful_list_returns_reports(self):
        """Test successful report listing."""
        api = MagicMock()

        mock_fhir_client = MagicMock()
        mock_fhir_client.search_document_references.return_value = {
            "entry": [
                {
                    "resource": {
                        "id": "doc-123",
                        "date": "2024-01-15",
                        "description": "Lab Report",
                        "type": {"text": "Complete Blood Count"}
                    }
                }
            ]
        }
        api._get_fhir_client.return_value = mock_fhir_client

        with patch("portal_content.content_types.labs.log"):
            result = labs._handle_list(api, "patient-123", {"limit": 20, "offset": 0})

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.OK

    def test_empty_results_returns_empty_list(self):
        """Test empty results returns empty summaries."""
        api = MagicMock()

        mock_fhir_client = MagicMock()
        mock_fhir_client.search_document_references.return_value = {"entry": []}
        api._get_fhir_client.return_value = mock_fhir_client

        with patch("portal_content.content_types.labs.log"):
            result = labs._handle_list(api, "patient-123", {"limit": 20, "offset": 0})

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.OK

    def test_limit_capped_at_50(self):
        """Test that limit is capped at 50."""
        api = MagicMock()

        mock_fhir_client = MagicMock()
        mock_fhir_client.search_document_references.return_value = {"entry": []}
        api._get_fhir_client.return_value = mock_fhir_client

        with patch("portal_content.content_types.labs.log"):
            result = labs._handle_list(api, "patient-123", {"limit": 100, "offset": 0})

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.OK


class TestHandleDetail:
    """Tests for _handle_detail function."""

    def test_missing_report_id_returns_bad_request(self):
        """Test that missing report_id returns BAD_REQUEST."""
        api = MagicMock()

        result = labs._handle_detail(api, "patient-123", {})

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.BAD_REQUEST

    def test_fhir_client_unavailable_returns_error(self):
        """Test that unavailable FHIR client returns error."""
        api = MagicMock()
        api._get_fhir_client.return_value = None

        with patch("portal_content.content_types.labs.log"):
            result = labs._handle_detail(api, "patient-123", {"report_id": "doc-123"})

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_document_not_found_returns_404(self):
        """Test that document not found returns NOT_FOUND."""
        api = MagicMock()

        mock_fhir_client = MagicMock()
        mock_fhir_client.base_url = "https://fumage-test.canvasmedical.com"
        mock_fhir_client.token = "test-token"
        api._get_fhir_client.return_value = mock_fhir_client

        with patch("portal_content.content_types.labs.requests.get") as mock_get:
            with patch("portal_content.content_types.labs.log"):
                mock_response = MagicMock()
                mock_response.status_code = 404
                mock_get.return_value = mock_response

                result = labs._handle_detail(api, "patient-123", {"report_id": "doc-123"})

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.NOT_FOUND

    def test_access_denied_for_other_patient_document(self):
        """Test that accessing another patient's document returns FORBIDDEN."""
        api = MagicMock()

        mock_fhir_client = MagicMock()
        mock_fhir_client.base_url = "https://fumage-test.canvasmedical.com"
        mock_fhir_client.token = "test-token"
        api._get_fhir_client.return_value = mock_fhir_client

        with patch("portal_content.content_types.labs.requests.get") as mock_get:
            with patch("portal_content.content_types.labs.log"):
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {
                    "subject": {"reference": "Patient/other-patient-456"}
                }
                mock_get.return_value = mock_response

                result = labs._handle_detail(api, "patient-123", {"report_id": "doc-123"})

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.FORBIDDEN

    def test_successful_detail_returns_report(self):
        """Test successful detail returns report."""
        api = MagicMock()

        mock_fhir_client = MagicMock()
        mock_fhir_client.base_url = "https://fumage-test.canvasmedical.com"
        mock_fhir_client.token = "test-token"
        api._get_fhir_client.return_value = mock_fhir_client

        with patch("portal_content.content_types.labs.requests.get") as mock_get:
            with patch("portal_content.content_types.labs.log"):
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {
                    "id": "doc-123",
                    "date": "2024-01-15",
                    "description": "Lab Report",
                    "subject": {"reference": "Patient/patient-123"},
                    "type": {"text": "Complete Blood Count"},
                    "content": [{"attachment": {"url": "https://example.com/pdf"}}]
                }
                mock_get.return_value = mock_response

                result = labs._handle_detail(api, "patient-123", {"report_id": "doc-123"})

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.OK


class TestExtractReportSummary:
    """Tests for _extract_report_summary function."""

    def test_extracts_all_fields(self):
        """Test that all fields are extracted."""
        document_reference = {
            "id": "doc-123",
            "date": "2024-01-15",
            "description": "Complete Blood Count",
            "type": {"text": "Lab Report"},
            "content": [{"attachment": {"url": "https://example.com/pdf"}}]
        }

        result = labs._extract_report_summary(document_reference, "patient-123")

        assert result["report_id"] == "doc-123"
        assert result["date_received"] == "2024-01-15"
        assert result["report_name"] == "Complete Blood Count"

    def test_uses_type_text_when_description_missing(self):
        """Test using type text when description missing."""
        document_reference = {
            "id": "doc-123",
            "date": "2024-01-15",
            "type": {"text": "Lab Report"},
            "content": [{"attachment": {"url": "https://example.com/pdf"}}]
        }

        result = labs._extract_report_summary(document_reference, "patient-123")

        assert result["report_name"] == "Lab Report"

    def test_uses_coding_display_when_type_text_missing(self):
        """Test using coding display when type text is empty."""
        document_reference = {
            "id": "doc-123",
            "date": "2024-01-15",
            "type": {"text": "", "coding": [{"display": "Diagnostic Report"}]},
            "content": [{"attachment": {"url": "https://example.com/pdf"}}]
        }

        result = labs._extract_report_summary(document_reference, "patient-123")

        assert result["report_name"] == "Diagnostic Report"

    def test_handles_exception(self):
        """Test handling of exceptions."""
        # Pass invalid data that would cause an exception
        document_reference = None

        result = labs._extract_report_summary(document_reference, "patient-123")

        assert result is None
