"""Tests for document queue application."""

from unittest.mock import MagicMock, patch

import pytest

from extend_lab_intake.applications.document_queue import DocumentQueueApplication
from extend_lab_intake.utils.constants import Secrets


class TestDocumentQueueApplication:
    """Tests for DocumentQueueApplication."""

    @pytest.fixture
    def app(self) -> DocumentQueueApplication:
        """Create a DocumentQueueApplication instance."""
        app = DocumentQueueApplication()
        app.secrets = {
            Secrets.AWS_ACCESS_KEY_ID: "test-key",
            Secrets.AWS_SECRET_ACCESS_KEY: "test-secret",
            Secrets.INBOUND_FAX_TOKEN: "test-token",
        }
        app.environment = {"CUSTOMER_IDENTIFIER": "test-instance"}
        return app

    @patch.object(DocumentQueueApplication, "_get_documents")
    @patch("extend_lab_intake.applications.document_queue.render_to_string")
    def test_on_open(
        self,
        mock_render: MagicMock,
        mock_get_docs: MagicMock,
        app: DocumentQueueApplication,
    ) -> None:
        """Test on_open launches modal."""
        mock_get_docs.return_value = []
        mock_render.return_value = "<html>Content</html>"

        result = app.on_open()

        mock_get_docs.assert_called_once()
        mock_render.assert_called_once()
        # Verify template context
        call_args = mock_render.call_args
        assert "documents" in call_args.args[1]
        assert "session_token" in call_args.args[1]
        assert "instance" in call_args.args[1]

    @patch("extend_lab_intake.applications.document_queue.S3Client")
    def test_get_documents_success(
        self, mock_s3_class: MagicMock, app: DocumentQueueApplication
    ) -> None:
        """Test getting documents from S3 index."""
        mock_s3 = MagicMock()
        mock_s3_class.return_value = mock_s3

        mock_s3.get_index.return_value = {
            "documents": [
                {
                    "intake_id": "abc123",
                    "filename": "report.pdf",
                    "status": "classified",
                    "classification_type": "Lipid Panel",
                    "received_at": "2024-01-15T10:00:00Z",
                    "size_bytes": 1024,
                }
            ]
        }

        documents = app._get_documents()

        assert len(documents) == 1
        assert documents[0]["intake_id"] == "abc123"
        assert documents[0]["filename"] == "report.pdf"
        assert documents[0]["status"] == "classified"
        assert documents[0]["classification_type"] == "Lipid Panel"
        assert documents[0]["size_display"] == "1.0 KB"

    @patch("extend_lab_intake.applications.document_queue.S3Client")
    def test_get_documents_multiple(
        self, mock_s3_class: MagicMock, app: DocumentQueueApplication
    ) -> None:
        """Test getting multiple documents from index."""
        mock_s3 = MagicMock()
        mock_s3_class.return_value = mock_s3

        mock_s3.get_index.return_value = {
            "documents": [
                {
                    "intake_id": "abc123",
                    "filename": "report1.pdf",
                    "status": "classified",
                    "classification_type": "Lipid Panel",
                    "received_at": "2024-01-15T10:00:00Z",
                    "size_bytes": 1024,
                },
                {
                    "intake_id": "def456",
                    "filename": "report2.pdf",
                    "status": "processed",
                    "classification_type": "CBC",
                    "received_at": "2024-01-16T10:00:00Z",
                    "size_bytes": 2048,
                },
            ]
        }

        documents = app._get_documents()

        assert len(documents) == 2
        # Should be sorted by received_at descending
        assert documents[0]["intake_id"] == "def456"  # More recent

    @patch("extend_lab_intake.applications.document_queue.S3Client")
    def test_get_documents_empty_index(
        self, mock_s3_class: MagicMock, app: DocumentQueueApplication
    ) -> None:
        """Test handling empty index."""
        mock_s3 = MagicMock()
        mock_s3_class.return_value = mock_s3

        mock_s3.get_index.return_value = {"documents": []}

        documents = app._get_documents()

        assert len(documents) == 0

    @patch("extend_lab_intake.applications.document_queue.S3Client")
    def test_get_documents_exception(
        self, mock_s3_class: MagicMock, app: DocumentQueueApplication
    ) -> None:
        """Test handling S3 exception."""
        mock_s3 = MagicMock()
        mock_s3_class.return_value = mock_s3

        mock_s3.get_index.side_effect = Exception("S3 error")

        documents = app._get_documents()

        assert documents == []

    def test_format_size_bytes(self, app: DocumentQueueApplication) -> None:
        """Test formatting bytes."""
        assert app._format_size(500) == "500 B"

    def test_format_size_kilobytes(self, app: DocumentQueueApplication) -> None:
        """Test formatting kilobytes."""
        assert app._format_size(2048) == "2.0 KB"

    def test_format_size_megabytes(self, app: DocumentQueueApplication) -> None:
        """Test formatting megabytes."""
        assert app._format_size(2 * 1024 * 1024) == "2.0 MB"

    @patch("extend_lab_intake.applications.document_queue.S3Client")
    def test_get_documents_various_statuses(
        self, mock_s3_class: MagicMock, app: DocumentQueueApplication
    ) -> None:
        """Test documents with various status values."""
        mock_s3 = MagicMock()
        mock_s3_class.return_value = mock_s3

        mock_s3.get_index.return_value = {
            "documents": [
                {
                    "intake_id": "abc123",
                    "filename": "report.pdf",
                    "status": "processed",
                    "classification_type": "Lipid Panel",
                    "received_at": "2024-01-15T10:00:00Z",
                    "size_bytes": 1024,
                },
                {
                    "intake_id": "def456",
                    "filename": "report2.pdf",
                    "status": "saved",
                    "classification_type": "CBC",
                    "received_at": "2024-01-14T10:00:00Z",
                    "size_bytes": 2048,
                },
                {
                    "intake_id": "ghi789",
                    "filename": "report3.pdf",
                    "status": "no_extractor",
                    "classification_type": "Unknown",
                    "received_at": "2024-01-13T10:00:00Z",
                    "size_bytes": 512,
                },
            ]
        }

        documents = app._get_documents()

        assert len(documents) == 3
        assert documents[0]["status"] == "processed"
        assert documents[1]["status"] == "saved"
        assert documents[2]["status"] == "no_extractor"

    @patch("extend_lab_intake.applications.document_queue.S3Client")
    def test_get_documents_missing_fields(
        self, mock_s3_class: MagicMock, app: DocumentQueueApplication
    ) -> None:
        """Test handling documents with missing fields."""
        mock_s3 = MagicMock()
        mock_s3_class.return_value = mock_s3

        mock_s3.get_index.return_value = {
            "documents": [
                {
                    "intake_id": "abc123",
                    # Missing filename, status, etc.
                }
            ]
        }

        documents = app._get_documents()

        assert len(documents) == 1
        assert documents[0]["intake_id"] == "abc123"
        assert documents[0]["filename"] == ""
        assert documents[0]["status"] == "unknown"
        assert documents[0]["classification_type"] == "unknown"
        assert documents[0]["size_display"] == "0 B"
