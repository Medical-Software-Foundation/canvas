"""Tests for S3 client."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from extend_lab_intake.utils.s3_client import S3Client


class TestS3Client:
    """Tests for S3Client."""

    @pytest.fixture
    def client(self) -> S3Client:
        """Create an S3Client instance."""
        return S3Client(
            aws_key="test-key",
            aws_secret="test-secret",
            bucket="test-bucket",
            region="us-west-2",
            instance="test-instance",
        )

    def test_is_ready_with_credentials(self, client: S3Client) -> None:
        """Test is_ready returns True when all credentials are set."""
        assert client.is_ready() is True

    def test_is_ready_without_credentials(self) -> None:
        """Test is_ready returns False when credentials are missing."""
        client = S3Client(
            aws_key="",
            aws_secret="",
            bucket="",
            region="",
            instance="",
        )
        assert client.is_ready() is False

    def test_prefixed_key(self, client: S3Client) -> None:
        """Test that object keys are properly prefixed."""
        key = client._prefixed_key("my-file.pdf")
        assert key == "test-instance-plugins/extend_lab_intake/my-file.pdf"

    def test_get_host(self, client: S3Client) -> None:
        """Test S3 host construction."""
        host = client.get_host()
        assert host == "test-bucket.s3.us-west-2.amazonaws.com"

    def test_generate_presigned_url_format(self, client: S3Client) -> None:
        """Test presigned URL has correct structure."""
        url = client.generate_presigned_url("test-file.pdf", expires_in=3600)

        assert "test-bucket.s3.us-west-2.amazonaws.com" in url
        assert "test-instance-plugins/extend_lab_intake/test-file.pdf" in url
        assert "X-Amz-Algorithm=AWS4-HMAC-SHA256" in url
        assert "X-Amz-Expires=3600" in url
        assert "X-Amz-Signature=" in url

    def test_upload_pdf_not_ready(self) -> None:
        """Test upload fails gracefully when not configured."""
        client = S3Client(
            aws_key="",
            aws_secret="",
            bucket="",
            region="",
            instance="",
        )

        response = client.upload_pdf("test.pdf", b"pdf-data")

        assert response.status_code == 503

    @patch("requests.put")
    def test_upload_pdf_success(
        self, mock_put: MagicMock, client: S3Client
    ) -> None:
        """Test successful PDF upload."""
        mock_put.return_value = MagicMock(status_code=200)

        response = client.upload_pdf("test.pdf", b"pdf-data")

        assert response.status_code == 200
        mock_put.assert_called_once()

    def test_delete_object_not_ready(self) -> None:
        """Test delete fails gracefully when not configured."""
        client = S3Client(
            aws_key="",
            aws_secret="",
            bucket="",
            region="",
            instance="",
        )

        response = client.delete_object("test.pdf")

        assert response.status_code == 503

    @patch("requests.delete")
    def test_delete_object_success(
        self, mock_delete: MagicMock, client: S3Client
    ) -> None:
        """Test successful object deletion."""
        mock_delete.return_value = MagicMock(status_code=204)

        response = client.delete_object("test.pdf")

        assert response.status_code == 204
        mock_delete.assert_called_once()

    def test_list_objects_not_ready(self) -> None:
        """Test list objects fails gracefully when not configured."""
        client = S3Client(
            aws_key="",
            aws_secret="",
            bucket="",
            region="",
            instance="",
        )

        result = client.list_objects("prefix/")

        assert result == []

    @patch("requests.get")
    def test_list_objects_success(
        self, mock_get: MagicMock, client: S3Client
    ) -> None:
        """Test successful object listing."""
        xml_response = """<?xml version="1.0" encoding="UTF-8"?>
        <ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
            <Contents>
                <Key>test-instance-plugins/extend_lab_intake/intake/123/file.pdf</Key>
                <Size>1024</Size>
                <LastModified>2024-01-15T10:00:00Z</LastModified>
            </Contents>
        </ListBucketResult>"""

        mock_get.return_value = MagicMock(
            status_code=200,
            content=xml_response.encode(),
        )

        result = client.list_objects("intake/")

        assert len(result) == 1
        assert result[0]["Key"] == "intake/123/file.pdf"
        assert result[0]["Size"] == 1024

    @patch("requests.get")
    def test_list_objects_error(
        self, mock_get: MagicMock, client: S3Client
    ) -> None:
        """Test list objects handles error response."""
        mock_get.return_value = MagicMock(status_code=500)

        result = client.list_objects("prefix/")

        assert result == []

    @patch("requests.get")
    def test_list_objects_exception(
        self, mock_get: MagicMock, client: S3Client
    ) -> None:
        """Test list objects handles exception."""
        mock_get.side_effect = Exception("Network error")

        result = client.list_objects("prefix/")

        assert result == []

    def test_upload_json_not_ready(self) -> None:
        """Test upload JSON fails gracefully when not configured."""
        client = S3Client(
            aws_key="",
            aws_secret="",
            bucket="",
            region="",
            instance="",
        )

        response = client.upload_json("test.json", {"key": "value"})

        assert response.status_code == 503

    @patch("requests.put")
    def test_upload_json_success(
        self, mock_put: MagicMock, client: S3Client
    ) -> None:
        """Test successful JSON upload."""
        mock_put.return_value = MagicMock(status_code=200)

        response = client.upload_json("test.json", {"key": "value"})

        assert response.status_code == 200
        mock_put.assert_called_once()

    def test_get_json_not_ready(self) -> None:
        """Test get JSON returns None when not configured."""
        client = S3Client(
            aws_key="",
            aws_secret="",
            bucket="",
            region="",
            instance="",
        )

        result = client.get_json("test.json")

        assert result is None

    @patch("requests.get")
    def test_get_json_success(
        self, mock_get: MagicMock, client: S3Client
    ) -> None:
        """Test successful JSON retrieval."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"key": "value"},
        )

        result = client.get_json("test.json")

        assert result == {"key": "value"}

    @patch("requests.get")
    def test_get_json_not_found(
        self, mock_get: MagicMock, client: S3Client
    ) -> None:
        """Test get JSON returns None when not found."""
        mock_get.return_value = MagicMock(status_code=404)

        result = client.get_json("test.json")

        assert result is None

    @patch("requests.get")
    def test_get_json_exception(
        self, mock_get: MagicMock, client: S3Client
    ) -> None:
        """Test get JSON handles exception."""
        mock_get.side_effect = Exception("Network error")

        result = client.get_json("test.json")

        assert result is None

    def test_get_object_not_ready(self) -> None:
        """Test get object returns None when not configured."""
        client = S3Client(
            aws_key="",
            aws_secret="",
            bucket="",
            region="",
            instance="",
        )

        result = client.get_object("test.pdf")

        assert result is None

    @patch("requests.get")
    def test_get_object_success(
        self, mock_get: MagicMock, client: S3Client
    ) -> None:
        """Test successful object retrieval."""
        mock_get.return_value = MagicMock(
            status_code=200,
            content=b"PDF content",
        )

        result = client.get_object("test.pdf")

        assert result == b"PDF content"

    @patch("requests.get")
    def test_get_object_not_found(
        self, mock_get: MagicMock, client: S3Client
    ) -> None:
        """Test get object returns None when not found."""
        mock_get.return_value = MagicMock(status_code=404)

        result = client.get_object("test.pdf")

        assert result is None

    @patch("requests.get")
    def test_get_object_exception(
        self, mock_get: MagicMock, client: S3Client
    ) -> None:
        """Test get object handles exception."""
        mock_get.side_effect = Exception("Network error")

        result = client.get_object("test.pdf")

        assert result is None

    def test_get_signature_key(self, client: S3Client) -> None:
        """Test signature key generation."""
        key = client._get_signature_key("20240115")

        # Just verify it returns bytes
        assert isinstance(key, bytes)
        assert len(key) == 32  # SHA256 produces 32 bytes

    def test_sign_request(self, client: S3Client) -> None:
        """Test request signing."""
        amz_date = "20240115T100000Z"
        canonical_request = "GET\n/\n\nhost:test\n\nhost\nhash"

        scope, signature = client._sign_request(amz_date, canonical_request)

        assert "20240115" in scope
        assert "us-west-2" in scope
        assert "s3" in scope
        assert isinstance(signature, str)
        assert len(signature) == 64  # SHA256 hex

    def test_build_headers_get(self, client: S3Client) -> None:
        """Test building headers for GET request."""
        headers = client._build_headers("test-key", method="GET")

        assert "Host" in headers
        assert "x-amz-date" in headers
        assert "x-amz-content-sha256" in headers
        assert "Authorization" in headers

    def test_build_headers_put_with_content_type(self, client: S3Client) -> None:
        """Test building headers for PUT request with content type."""
        headers = client._build_headers(
            "test-key",
            method="PUT",
            data=b"data",
            content_type="application/pdf",
        )

        assert "Content-Type" in headers
        assert headers["Content-Type"] == "application/pdf"

    @patch("requests.get")
    def test_list_objects_preserves_non_prefixed_keys(
        self, mock_get: MagicMock, client: S3Client
    ) -> None:
        """Test list objects handles keys without expected prefix."""
        xml_response = """<?xml version="1.0" encoding="UTF-8"?>
        <ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
            <Contents>
                <Key>other-prefix/file.pdf</Key>
                <Size>512</Size>
            </Contents>
        </ListBucketResult>"""

        mock_get.return_value = MagicMock(
            status_code=200,
            content=xml_response.encode(),
        )

        result = client.list_objects("intake/")

        assert len(result) == 1
        assert result[0]["Key"] == "other-prefix/file.pdf"

    # Index management tests

    @patch.object(S3Client, "get_json")
    def test_get_index_success(
        self, mock_get_json: MagicMock, client: S3Client
    ) -> None:
        """Test getting index from S3."""
        mock_get_json.return_value = {
            "documents": [
                {"intake_id": "abc123", "filename": "test.pdf"}
            ]
        }

        result = client.get_index()

        mock_get_json.assert_called_once_with("intake/index.json")
        assert len(result["documents"]) == 1
        assert result["documents"][0]["intake_id"] == "abc123"

    @patch.object(S3Client, "get_json")
    def test_get_index_not_found(
        self, mock_get_json: MagicMock, client: S3Client
    ) -> None:
        """Test get_index returns empty structure when not found."""
        mock_get_json.return_value = None

        result = client.get_index()

        assert result == {"documents": []}

    @patch.object(S3Client, "upload_json")
    def test_save_index_success(
        self, mock_upload_json: MagicMock, client: S3Client
    ) -> None:
        """Test saving index to S3."""
        mock_upload_json.return_value = MagicMock(status_code=200)

        index = {"documents": [{"intake_id": "abc123"}]}
        result = client.save_index(index)

        mock_upload_json.assert_called_once_with("intake/index.json", index)
        assert result is True

    @patch.object(S3Client, "upload_json")
    def test_save_index_failure(
        self, mock_upload_json: MagicMock, client: S3Client
    ) -> None:
        """Test save_index returns False on failure."""
        mock_upload_json.return_value = MagicMock(status_code=500)

        result = client.save_index({"documents": []})

        assert result is False

    @patch.object(S3Client, "get_index")
    @patch.object(S3Client, "save_index")
    def test_add_to_index(
        self, mock_save: MagicMock, mock_get: MagicMock, client: S3Client
    ) -> None:
        """Test adding a document to the index."""
        mock_get.return_value = {"documents": []}
        mock_save.return_value = True

        result = client.add_to_index(
            intake_id="abc123",
            filename="test.pdf",
            status="classified",
            classification_type="Lipid Panel",
            received_at="2024-01-15T10:00:00Z",
            size_bytes=1024,
        )

        assert result is True
        saved_index = mock_save.call_args[0][0]
        assert len(saved_index["documents"]) == 1
        assert saved_index["documents"][0]["intake_id"] == "abc123"

    @patch.object(S3Client, "get_index")
    @patch.object(S3Client, "save_index")
    def test_add_to_index_replaces_existing(
        self, mock_save: MagicMock, mock_get: MagicMock, client: S3Client
    ) -> None:
        """Test adding a document with same ID replaces existing."""
        mock_get.return_value = {
            "documents": [
                {
                    "intake_id": "abc123",
                    "filename": "old.pdf",
                    "status": "classified",
                }
            ]
        }
        mock_save.return_value = True

        result = client.add_to_index(
            intake_id="abc123",
            filename="new.pdf",
            status="processed",
            classification_type="Lipid Panel",
            received_at="2024-01-15T10:00:00Z",
            size_bytes=2048,
        )

        assert result is True
        saved_index = mock_save.call_args[0][0]
        assert len(saved_index["documents"]) == 1
        assert saved_index["documents"][0]["filename"] == "new.pdf"
        assert saved_index["documents"][0]["status"] == "processed"

    @patch.object(S3Client, "get_index")
    @patch.object(S3Client, "save_index")
    def test_update_index_status(
        self, mock_save: MagicMock, mock_get: MagicMock, client: S3Client
    ) -> None:
        """Test updating document status in the index."""
        mock_get.return_value = {
            "documents": [
                {"intake_id": "abc123", "status": "classified"}
            ]
        }
        mock_save.return_value = True

        result = client.update_index_status("abc123", "processed")

        assert result is True
        saved_index = mock_save.call_args[0][0]
        assert saved_index["documents"][0]["status"] == "processed"

    @patch.object(S3Client, "get_index")
    @patch.object(S3Client, "save_index")
    def test_update_index_status_not_found(
        self, mock_save: MagicMock, mock_get: MagicMock, client: S3Client
    ) -> None:
        """Test update_index_status returns False when not found."""
        mock_get.return_value = {"documents": []}

        result = client.update_index_status("abc123", "processed")

        assert result is False
        mock_save.assert_not_called()

    @patch.object(S3Client, "get_index")
    @patch.object(S3Client, "save_index")
    def test_remove_from_index(
        self, mock_save: MagicMock, mock_get: MagicMock, client: S3Client
    ) -> None:
        """Test removing a document from the index."""
        mock_get.return_value = {
            "documents": [
                {"intake_id": "abc123"},
                {"intake_id": "def456"},
            ]
        }
        mock_save.return_value = True

        result = client.remove_from_index("abc123")

        assert result is True
        saved_index = mock_save.call_args[0][0]
        assert len(saved_index["documents"]) == 1
        assert saved_index["documents"][0]["intake_id"] == "def456"

    @patch.object(S3Client, "get_index")
    @patch.object(S3Client, "save_index")
    def test_remove_from_index_not_found(
        self, mock_save: MagicMock, mock_get: MagicMock, client: S3Client
    ) -> None:
        """Test remove_from_index returns True when not found (idempotent)."""
        mock_get.return_value = {"documents": []}

        result = client.remove_from_index("abc123")

        assert result is True
        mock_save.assert_not_called()
