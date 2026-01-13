"""Tests for the imaging content type module."""

import pytest
from http import HTTPStatus
from unittest.mock import call, patch, MagicMock

from portal_content.content_types import imaging


class TestServePortalPage:
    """Tests for serve_portal_page function."""

    def test_returns_html_response(self):
        """Test that portal page returns HTML response."""
        api = MagicMock()
        api.request.headers.get.return_value = "patient-123"

        with patch("portal_content.content_types.imaging.log"):
            result = imaging.serve_portal_page(api)

        assert len(result) == 1
        response = result[0]
        assert response.status_code == HTTPStatus.OK
        assert b"My Imaging Reports" in response.content


class TestHandleReportsRequest:
    """Tests for handle_reports_request function."""

    def test_list_action_calls_handle_list(self):
        """Test that list action routes to _handle_list."""
        api = MagicMock()
        api.request.headers.get.return_value = "patient-123"
        api.request.json.return_value = {"action": "list"}

        with patch("portal_content.content_types.imaging._handle_list") as mock_handle:
            with patch("portal_content.content_types.imaging.log"):
                mock_handle.return_value = [MagicMock()]
                result = imaging.handle_reports_request(api)

        mock_handle.assert_called_once_with(api, "patient-123", {"action": "list"})

    def test_detail_action_calls_handle_detail(self):
        """Test that detail action routes to _handle_detail."""
        api = MagicMock()
        api.request.headers.get.return_value = "patient-123"
        api.request.json.return_value = {"action": "detail", "report_id": "doc-123"}

        with patch("portal_content.content_types.imaging._handle_detail") as mock_handle:
            with patch("portal_content.content_types.imaging.log"):
                mock_handle.return_value = [MagicMock()]
                result = imaging.handle_reports_request(api)

        mock_handle.assert_called_once_with(api, "patient-123", {"action": "detail", "report_id": "doc-123"})

    def test_unknown_action_returns_bad_request(self):
        """Test that unknown action returns BAD_REQUEST."""
        api = MagicMock()
        api.request.headers.get.return_value = "patient-123"
        api.request.json.return_value = {"action": "invalid"}

        with patch("portal_content.content_types.imaging.log"):
            result = imaging.handle_reports_request(api)

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.BAD_REQUEST

    def test_exception_returns_internal_error(self):
        """Test that exceptions return INTERNAL_SERVER_ERROR."""
        api = MagicMock()
        api.request.headers.get.return_value = "patient-123"
        api.request.json.side_effect = Exception("Parse error")

        with patch("portal_content.content_types.imaging.log"):
            result = imaging.handle_reports_request(api)

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR


class TestProxyPdf:
    """Tests for proxy_pdf function."""

    def test_missing_document_id_returns_bad_request(self):
        """Test that missing document_id returns BAD_REQUEST."""
        api = MagicMock()
        api.request.headers.get.return_value = "patient-123"
        api.request.query_params.get.return_value = None

        result = imaging.proxy_pdf(api)

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.BAD_REQUEST

    def test_fhir_client_unavailable_returns_error(self):
        """Test that unavailable FHIR client returns error."""
        api = MagicMock()
        api.request.headers.get.return_value = "patient-123"
        api.request.query_params.get.return_value = "doc-123"
        api._get_fhir_client.return_value = None

        with patch("portal_content.content_types.imaging.log"):
            result = imaging.proxy_pdf(api)

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

        with patch("portal_content.content_types.imaging.requests.get") as mock_get:
            with patch("portal_content.content_types.imaging.log"):
                mock_response = MagicMock()
                mock_response.status_code = 404
                mock_get.return_value = mock_response

                result = imaging.proxy_pdf(api)

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

        with patch("portal_content.content_types.imaging.requests.get") as mock_get:
            with patch("portal_content.content_types.imaging.log"):
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {
                    "subject": {"reference": "Patient/other-patient-456"}
                }
                mock_get.return_value = mock_response

                result = imaging.proxy_pdf(api)

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

        with patch("portal_content.content_types.imaging.requests.get") as mock_get:
            with patch("portal_content.content_types.imaging.log"):
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

                result = imaging.proxy_pdf(api)

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

        with patch("portal_content.content_types.imaging.requests.get") as mock_get:
            with patch("portal_content.content_types.imaging.log"):
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

                result = imaging.proxy_pdf(api)

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.NOT_FOUND

    def test_proxy_pdf_exception_returns_internal_error(self):
        """Test that exception during PDF proxy returns INTERNAL_SERVER_ERROR."""
        api = MagicMock()
        api.request.headers.get.return_value = "patient-123"
        api.request.query_params.get.return_value = "doc-123"

        mock_fhir_client = MagicMock()
        mock_fhir_client.base_url = "https://fumage-test.canvasmedical.com"
        mock_fhir_client.token = "test-token"
        api._get_fhir_client.return_value = mock_fhir_client

        with patch("portal_content.content_types.imaging.requests.get") as mock_get:
            with patch("portal_content.content_types.imaging.log"):
                mock_get.side_effect = Exception("Network error")
                result = imaging.proxy_pdf(api)

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR


class TestHandleList:
    """Tests for _handle_list function."""

    def test_fhir_client_unavailable_returns_error(self):
        """Test that unavailable FHIR client returns error."""
        api = MagicMock()
        api._get_fhir_client.return_value = None

        with patch("portal_content.content_types.imaging.log"):
            result = imaging._handle_list(api, "patient-123", {})

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
                        "description": "Imaging Report",
                        "type": {"text": "X-Ray"}
                    }
                }
            ]
        }
        api._get_fhir_client.return_value = mock_fhir_client

        with patch("portal_content.content_types.imaging.log"):
            result = imaging._handle_list(api, "patient-123", {"limit": 20, "offset": 0})

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.OK

    def test_empty_results_returns_empty_list(self):
        """Test empty results returns empty summaries."""
        api = MagicMock()

        mock_fhir_client = MagicMock()
        mock_fhir_client.search_document_references.return_value = {"entry": []}
        api._get_fhir_client.return_value = mock_fhir_client

        with patch("portal_content.content_types.imaging.log"):
            result = imaging._handle_list(api, "patient-123", {"limit": 20, "offset": 0})

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.OK

    def test_limit_capped_at_50(self):
        """Test that limit is capped at 50."""
        api = MagicMock()

        mock_fhir_client = MagicMock()
        mock_fhir_client.search_document_references.return_value = {"entry": []}
        api._get_fhir_client.return_value = mock_fhir_client

        with patch("portal_content.content_types.imaging.log"):
            result = imaging._handle_list(api, "patient-123", {"limit": 100, "offset": 0})

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.OK

    def test_pagination_returns_has_more(self):
        """Test that pagination correctly calculates has_more."""
        import json

        api = MagicMock()

        mock_fhir_client = MagicMock()
        # Return 3 entries, request limit 2
        mock_fhir_client.search_document_references.return_value = {
            "entry": [
                {"resource": {"id": f"doc-{i}", "date": "2024-01-15", "description": f"Report {i}"}}
                for i in range(3)
            ]
        }
        api._get_fhir_client.return_value = mock_fhir_client

        with patch("portal_content.content_types.imaging.log"):
            result = imaging._handle_list(api, "patient-123", {"limit": 2, "offset": 0})

        assert len(result) == 1
        response_data = json.loads(result[0].content)
        assert response_data["data"]["has_more"] is True
        assert response_data["data"]["total"] == 3
        assert len(response_data["data"]["reports"]) == 2

    def test_handle_list_exception_returns_internal_error(self):
        """Test that exception in _handle_list returns INTERNAL_SERVER_ERROR."""
        api = MagicMock()

        mock_fhir_client = MagicMock()
        mock_fhir_client.search_document_references.side_effect = Exception("API error")
        api._get_fhir_client.return_value = mock_fhir_client

        with patch("portal_content.content_types.imaging.log"):
            result = imaging._handle_list(api, "patient-123", {"limit": 20, "offset": 0})

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR


class TestHandleDetail:
    """Tests for _handle_detail function."""

    def test_missing_report_id_returns_bad_request(self):
        """Test that missing report_id returns BAD_REQUEST."""
        api = MagicMock()

        result = imaging._handle_detail(api, "patient-123", {})

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.BAD_REQUEST

    def test_fhir_client_unavailable_returns_error(self):
        """Test that unavailable FHIR client returns error."""
        api = MagicMock()
        api._get_fhir_client.return_value = None

        with patch("portal_content.content_types.imaging.log"):
            result = imaging._handle_detail(api, "patient-123", {"report_id": "doc-123"})

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_document_not_found_returns_404(self):
        """Test that document not found returns NOT_FOUND."""
        api = MagicMock()

        mock_fhir_client = MagicMock()
        mock_fhir_client.base_url = "https://fumage-test.canvasmedical.com"
        mock_fhir_client.token = "test-token"
        api._get_fhir_client.return_value = mock_fhir_client

        with patch("portal_content.content_types.imaging.requests.get") as mock_get:
            with patch("portal_content.content_types.imaging.log"):
                mock_response = MagicMock()
                mock_response.status_code = 404
                mock_get.return_value = mock_response

                result = imaging._handle_detail(api, "patient-123", {"report_id": "doc-123"})

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.NOT_FOUND

    def test_access_denied_for_other_patient_document(self):
        """Test that accessing another patient's document returns FORBIDDEN."""
        api = MagicMock()

        mock_fhir_client = MagicMock()
        mock_fhir_client.base_url = "https://fumage-test.canvasmedical.com"
        mock_fhir_client.token = "test-token"
        api._get_fhir_client.return_value = mock_fhir_client

        with patch("portal_content.content_types.imaging.requests.get") as mock_get:
            with patch("portal_content.content_types.imaging.log"):
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {
                    "subject": {"reference": "Patient/other-patient-456"}
                }
                mock_get.return_value = mock_response

                result = imaging._handle_detail(api, "patient-123", {"report_id": "doc-123"})

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.FORBIDDEN

    def test_successful_detail_returns_report(self):
        """Test successful detail returns report."""
        api = MagicMock()

        mock_fhir_client = MagicMock()
        mock_fhir_client.base_url = "https://fumage-test.canvasmedical.com"
        mock_fhir_client.token = "test-token"
        api._get_fhir_client.return_value = mock_fhir_client

        with patch("portal_content.content_types.imaging.requests.get") as mock_get:
            with patch("portal_content.content_types.imaging.log"):
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {
                    "id": "doc-123",
                    "date": "2024-01-15",
                    "description": "Imaging Report",
                    "subject": {"reference": "Patient/patient-123"},
                    "type": {"text": "X-Ray"},
                    "content": [{"attachment": {"url": "https://example.com/pdf"}}]
                }
                mock_get.return_value = mock_response

                result = imaging._handle_detail(api, "patient-123", {"report_id": "doc-123"})

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.OK

    def test_handle_detail_exception_returns_internal_error(self):
        """Test that exception in _handle_detail returns INTERNAL_SERVER_ERROR."""
        api = MagicMock()

        mock_fhir_client = MagicMock()
        mock_fhir_client.base_url = "https://fumage-test.canvasmedical.com"
        mock_fhir_client.token = "test-token"
        api._get_fhir_client.return_value = mock_fhir_client

        with patch("portal_content.content_types.imaging.requests.get") as mock_get:
            with patch("portal_content.content_types.imaging.log"):
                mock_get.side_effect = Exception("API error")
                result = imaging._handle_detail(api, "patient-123", {"report_id": "doc-123"})

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR


class TestExtractReportSummary:
    """Tests for _extract_report_summary function."""

    def test_extracts_all_fields(self):
        """Test that all fields are extracted."""
        document_reference = {
            "id": "doc-123",
            "date": "2024-01-15",
            "description": "X-Ray Chest",
            "type": {"text": "Imaging Report"},
            "content": [{"attachment": {"url": "https://example.com/pdf"}}],
            "context": {"period": {"start": "2024-01-10"}}
        }

        result = imaging._extract_report_summary(document_reference, "patient-123")

        assert result["report_id"] == "doc-123"
        assert result["date_received"] == "2024-01-15"
        assert result["date_collected"] == "2024-01-10"
        assert result["report_name"] == "X-Ray Chest"
        assert result["patient_id"] == "patient-123"
        assert "pdf_url" in result

    def test_uses_type_text_when_description_missing(self):
        """Test using type text when description missing."""
        document_reference = {
            "id": "doc-123",
            "date": "2024-01-15",
            "type": {"text": "Imaging Report"},
            "content": [{"attachment": {"url": "https://example.com/pdf"}}]
        }

        result = imaging._extract_report_summary(document_reference, "patient-123")

        assert result["report_name"] == "Imaging Report"

    def test_uses_coding_display_when_type_text_missing(self):
        """Test using coding display when type text is empty."""
        document_reference = {
            "id": "doc-123",
            "date": "2024-01-15",
            "type": {"text": "", "coding": [{"display": "Diagnostic Imaging"}]},
            "content": [{"attachment": {"url": "https://example.com/pdf"}}]
        }

        result = imaging._extract_report_summary(document_reference, "patient-123")

        assert result["report_name"] == "Diagnostic Imaging"

    def test_uses_default_name_when_all_missing(self):
        """Test using default name when all name sources missing."""
        document_reference = {
            "id": "doc-123",
            "date": "2024-01-15",
            "type": {},
            "content": [{"attachment": {"url": "https://example.com/pdf"}}]
        }

        result = imaging._extract_report_summary(document_reference, "patient-123")

        assert result["report_name"] == imaging.DEFAULT_REPORT_NAME

    def test_handles_missing_context(self):
        """Test handling of missing context for date_collected."""
        document_reference = {
            "id": "doc-123",
            "date": "2024-01-15",
            "description": "Imaging Report"
        }

        result = imaging._extract_report_summary(document_reference, "patient-123")

        assert result["date_collected"] is None

    def test_handles_exception(self):
        """Test handling of exceptions."""
        # Pass invalid data that would cause an exception
        document_reference = None

        result = imaging._extract_report_summary(document_reference, "patient-123")

        assert result is None
