"""Tests for the FHIR client."""

import pytest
from unittest.mock import call, patch, MagicMock

from portal_content.shared.fhir_client import FHIRClient


class TestFHIRClientInit:
    """Tests for FHIRClient initialization."""

    def test_init_strips_trailing_slash(self):
        """Test that trailing slash is stripped from base_url."""
        client = FHIRClient("https://example.com/", "test-token")

        assert client.base_url == "https://example.com"
        assert client.token == "test-token"

    def test_init_preserves_url_without_slash(self):
        """Test that URL without trailing slash is preserved."""
        client = FHIRClient("https://example.com", "test-token")

        assert client.base_url == "https://example.com"
        assert client.token == "test-token"


class TestSearchDiagnosticReports:
    """Tests for search_diagnostic_reports method."""

    def test_search_with_patient_id_only(self):
        """Test search with only patient_id parameter."""
        client = FHIRClient("https://fumage-test.canvasmedical.com", "test-token")

        with patch("portal_content.shared.fhir_client.requests.get") as mock_get:
            with patch("portal_content.shared.fhir_client.log"):
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {"resourceType": "Bundle", "entry": []}
                mock_get.return_value = mock_response

                result = client.search_diagnostic_reports(patient_id="patient-123")

        assert result == {"resourceType": "Bundle", "entry": []}
        mock_get.assert_called_once_with(
            "https://fumage-test.canvasmedical.com/DiagnosticReport",
            params={"patient": "patient-123"},
            headers={"Authorization": "Bearer test-token", "Accept": "application/json"},
        )

    def test_search_with_all_params(self):
        """Test search with all optional parameters."""
        client = FHIRClient("https://fumage-test.canvasmedical.com", "test-token")

        with patch("portal_content.shared.fhir_client.requests.get") as mock_get:
            with patch("portal_content.shared.fhir_client.log"):
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {
                    "resourceType": "Bundle",
                    "entry": [{"resource": {"id": "report-1"}}],
                }
                mock_get.return_value = mock_response

                result = client.search_diagnostic_reports(
                    patient_id="patient-123",
                    status="final",
                    category="LAB",
                    date="2024-01-01",
                )

        assert len(result["entry"]) == 1
        mock_get.assert_called_once_with(
            "https://fumage-test.canvasmedical.com/DiagnosticReport",
            params={
                "patient": "patient-123",
                "status": "final",
                "category": "LAB",
                "date": "2024-01-01",
            },
            headers={"Authorization": "Bearer test-token", "Accept": "application/json"},
        )

    def test_search_handles_non_200_response(self):
        """Test that non-200 response is logged and raises."""
        client = FHIRClient("https://fumage-test.canvasmedical.com", "test-token")

        with patch("portal_content.shared.fhir_client.requests.get") as mock_get:
            with patch("portal_content.shared.fhir_client.log") as mock_log:
                mock_response = MagicMock()
                mock_response.status_code = 404
                mock_response.text = "Not found"
                mock_response.raise_for_status.side_effect = Exception("404 Not Found")
                mock_get.return_value = mock_response

                result = client.search_diagnostic_reports(patient_id="patient-123")

        assert result == {"resourceType": "Bundle", "entry": []}
        # Verify error was logged
        error_calls = [c for c in mock_log.mock_calls if c[0] == "error"]
        assert len(error_calls) >= 1

    def test_search_handles_exception(self):
        """Test that exceptions are caught and return empty bundle."""
        client = FHIRClient("https://fumage-test.canvasmedical.com", "test-token")

        with patch("portal_content.shared.fhir_client.requests.get") as mock_get:
            with patch("portal_content.shared.fhir_client.log") as mock_log:
                mock_get.side_effect = Exception("Network error")

                result = client.search_diagnostic_reports(patient_id="patient-123")

        assert result == {"resourceType": "Bundle", "entry": []}
        error_calls = [c for c in mock_log.mock_calls if c[0] == "error"]
        assert len(error_calls) >= 1


class TestSearchDocumentReferences:
    """Tests for search_document_references method."""

    def test_search_with_patient_id_only(self):
        """Test search with only patient_id parameter."""
        client = FHIRClient("https://fumage-test.canvasmedical.com", "test-token")

        with patch("portal_content.shared.fhir_client.requests.get") as mock_get:
            with patch("portal_content.shared.fhir_client.log"):
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {"resourceType": "Bundle", "entry": []}
                mock_get.return_value = mock_response

                result = client.search_document_references(patient_id="patient-123")

        assert result == {"resourceType": "Bundle", "entry": []}
        mock_get.assert_called_once_with(
            "https://fumage-test.canvasmedical.com/DocumentReference",
            params={"patient": "patient-123"},
            headers={"Authorization": "Bearer test-token", "Accept": "application/json"},
        )

    def test_search_with_all_params(self):
        """Test search with all optional parameters."""
        client = FHIRClient("https://fumage-test.canvasmedical.com", "test-token")

        with patch("portal_content.shared.fhir_client.requests.get") as mock_get:
            with patch("portal_content.shared.fhir_client.log"):
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {"resourceType": "Bundle", "entry": []}
                mock_get.return_value = mock_response

                result = client.search_document_references(
                    patient_id="patient-123",
                    status="current",
                    category="educationalmaterial",
                    type="11488-4",
                    encounter="encounter-456",
                    date="2024-01-01",
                )

        mock_get.assert_called_once_with(
            "https://fumage-test.canvasmedical.com/DocumentReference",
            params={
                "patient": "patient-123",
                "status": "current",
                "category": "educationalmaterial",
                "type": "11488-4",
                "encounter": "encounter-456",
                "date": "2024-01-01",
            },
            headers={"Authorization": "Bearer test-token", "Accept": "application/json"},
        )

    def test_search_handles_exception(self):
        """Test that exceptions are caught and return empty bundle."""
        client = FHIRClient("https://fumage-test.canvasmedical.com", "test-token")

        with patch("portal_content.shared.fhir_client.requests.get") as mock_get:
            with patch("portal_content.shared.fhir_client.log"):
                mock_get.side_effect = Exception("Network error")

                result = client.search_document_references(patient_id="patient-123")

        assert result == {"resourceType": "Bundle", "entry": []}


class TestGetDocumentContentUrl:
    """Tests for get_document_content_url method."""

    def test_extracts_url_from_valid_document(self):
        """Test URL extraction from a valid DocumentReference."""
        client = FHIRClient("https://fumage-test.canvasmedical.com", "test-token")
        doc_ref = {
            "content": [{"attachment": {"url": "https://example.com/doc.pdf", "contentType": "application/pdf"}}]
        }

        result = client.get_document_content_url(doc_ref)

        assert result == "https://example.com/doc.pdf"

    def test_returns_none_for_empty_content(self):
        """Test returns None when content is empty."""
        client = FHIRClient("https://fumage-test.canvasmedical.com", "test-token")
        doc_ref = {"content": []}

        result = client.get_document_content_url(doc_ref)

        assert result is None

    def test_returns_none_for_missing_content(self):
        """Test returns None when content key is missing."""
        client = FHIRClient("https://fumage-test.canvasmedical.com", "test-token")
        doc_ref = {}

        result = client.get_document_content_url(doc_ref)

        assert result is None

    def test_returns_none_for_missing_url(self):
        """Test returns None when URL is missing from attachment."""
        client = FHIRClient("https://fumage-test.canvasmedical.com", "test-token")
        doc_ref = {"content": [{"attachment": {"contentType": "application/pdf"}}]}

        result = client.get_document_content_url(doc_ref)

        assert result is None

    def test_handles_exception(self):
        """Test graceful handling of exceptions."""
        client = FHIRClient("https://fumage-test.canvasmedical.com", "test-token")

        with patch("portal_content.shared.fhir_client.log"):
            # Pass a non-dict that will cause an error
            result = client.get_document_content_url(None)

        assert result is None
