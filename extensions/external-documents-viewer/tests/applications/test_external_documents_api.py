import json
from http import HTTPStatus
from unittest.mock import MagicMock, call, patch

from canvas_sdk.effects.simple_api import JSONResponse
from external_documents_viewer.applications.external_documents_api import ExternalDocumentsAPI


class TestExternalDocumentsAPIClient:
    """Tests for the S3 client helper method."""

    def test_s3_client_uses_secrets(self, mock_secrets: dict[str, str]) -> None:
        """_s3_client() should construct S3 with credentials from secrets."""
        handler = ExternalDocumentsAPI.__new__(ExternalDocumentsAPI)
        handler.secrets = mock_secrets

        with patch("external_documents_viewer.applications.external_documents_api.S3") as mock_s3_class:
            with patch(
                "external_documents_viewer.applications.external_documents_api.S3Credentials"
            ) as mock_creds_class:
                mock_creds_instance = MagicMock()
                mock_creds_class.return_value = mock_creds_instance
                mock_s3_instance = MagicMock()
                mock_s3_class.return_value = mock_s3_instance

                result = handler._s3_client()

                assert mock_creds_class.mock_calls == [
                    call(
                        key="test-access-key",
                        secret="test-secret-key",
                        region="us-west-2",
                        bucket="test-bucket",
                    )
                ]
                assert mock_s3_class.mock_calls == [call(mock_creds_instance)]
                assert mock_creds_instance.mock_calls == []
                assert result is mock_s3_instance


class TestGetDocumentUrl:
    """Tests for the GET /document-url/<s3_key> endpoint."""

    def test_returns_presigned_url(self, mock_secrets: dict[str, str]) -> None:
        """Should return a JSONResponse with the presigned URL."""
        handler = ExternalDocumentsAPI.__new__(ExternalDocumentsAPI)
        handler.secrets = {**mock_secrets, "S3_PREFIX": "legacy_emr_documents"}
        handler.request = MagicMock(path_params={"s3_key": "patient_data%2FDIR%2Ffile.pdf"})

        presigned = "https://bucket.s3.amazonaws.com/signed?X-Amz-Signature=abc"
        mock_s3_instance = MagicMock()
        mock_s3_instance.is_ready.return_value = True
        mock_s3_instance.generate_presigned_url.return_value = presigned

        with patch("external_documents_viewer.applications.external_documents_api.S3") as mock_s3_class:
            with patch(
                "external_documents_viewer.applications.external_documents_api.S3Credentials"
            ) as mock_creds_class:
                mock_creds_instance = MagicMock()
                mock_creds_class.return_value = mock_creds_instance
                mock_s3_class.return_value = mock_s3_instance

                effects = handler.get_document_url()

                assert mock_creds_class.mock_calls == [
                    call(
                        key="test-access-key",
                        secret="test-secret-key",
                        region="us-west-2",
                        bucket="test-bucket",
                    )
                ]
                assert mock_s3_class.mock_calls == [
                    call(mock_creds_instance),
                    call().is_ready(),
                    call().generate_presigned_url(
                        "legacy_emr_documents/patient_data/DIR/file.pdf",
                        expiration=3600,
                    ),
                ]
                assert mock_creds_instance.mock_calls == []
                assert mock_s3_instance.mock_calls == [
                    call.is_ready(),
                    call.generate_presigned_url(
                        "legacy_emr_documents/patient_data/DIR/file.pdf",
                        expiration=3600,
                    ),
                ]
                assert handler.request.mock_calls == []

                assert len(effects) == 1
                response = effects[0]
                assert isinstance(response, JSONResponse)
                assert response.status_code == HTTPStatus.OK
                assert json.loads(response.content) == {"url": presigned}

    def test_decodes_percent_encoded_key(self, mock_secrets: dict[str, str]) -> None:
        """URL-encoded slashes in path param must be decoded before building S3 key."""
        handler = ExternalDocumentsAPI.__new__(ExternalDocumentsAPI)
        handler.secrets = {**mock_secrets, "S3_PREFIX": "pfx"}
        handler.request = MagicMock(path_params={"s3_key": "a%2Fb%2Fc.pdf"})

        mock_s3_instance = MagicMock()
        mock_s3_instance.is_ready.return_value = True
        mock_s3_instance.generate_presigned_url.return_value = "https://example.com/signed"

        with patch("external_documents_viewer.applications.external_documents_api.S3") as mock_s3_class:
            with patch(
                "external_documents_viewer.applications.external_documents_api.S3Credentials"
            ) as mock_creds_class:
                mock_creds_class.return_value = MagicMock()
                mock_s3_class.return_value = mock_s3_instance

                handler.get_document_url()

                assert mock_s3_instance.mock_calls == [
                    call.is_ready(),
                    call.generate_presigned_url("pfx/a/b/c.pdf", expiration=3600),
                ]
                assert handler.request.mock_calls == []

    def test_no_prefix_omits_leading_slash(self, mock_secrets: dict[str, str]) -> None:
        """When S3_PREFIX is empty, the full key should not start with /."""
        handler = ExternalDocumentsAPI.__new__(ExternalDocumentsAPI)
        handler.secrets = {**mock_secrets, "S3_PREFIX": ""}
        handler.request = MagicMock(path_params={"s3_key": "doc.pdf"})

        mock_s3_instance = MagicMock()
        mock_s3_instance.is_ready.return_value = True
        mock_s3_instance.generate_presigned_url.return_value = "https://example.com/signed"

        with patch("external_documents_viewer.applications.external_documents_api.S3") as mock_s3_class:
            with patch(
                "external_documents_viewer.applications.external_documents_api.S3Credentials"
            ) as mock_creds_class:
                mock_creds_class.return_value = MagicMock()
                mock_s3_class.return_value = mock_s3_instance

                handler.get_document_url()

                assert mock_s3_instance.mock_calls == [
                    call.is_ready(),
                    call.generate_presigned_url("doc.pdf", expiration=3600),
                ]

    def test_s3_not_ready_returns_503(self, mock_secrets: dict[str, str]) -> None:
        """When S3 client is not ready, return 503 SERVICE_UNAVAILABLE."""
        handler = ExternalDocumentsAPI.__new__(ExternalDocumentsAPI)
        handler.secrets = {**mock_secrets, "S3_PREFIX": ""}
        handler.request = MagicMock(path_params={"s3_key": "doc.pdf"})

        mock_s3_instance = MagicMock()
        mock_s3_instance.is_ready.return_value = False

        with patch("external_documents_viewer.applications.external_documents_api.S3") as mock_s3_class:
            with patch(
                "external_documents_viewer.applications.external_documents_api.S3Credentials"
            ) as mock_creds_class:
                mock_creds_class.return_value = MagicMock()
                mock_s3_class.return_value = mock_s3_instance

                effects = handler.get_document_url()

                assert mock_s3_instance.mock_calls == [call.is_ready()]
                assert len(effects) == 1
                response = effects[0]
                assert isinstance(response, JSONResponse)
                assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
                assert json.loads(response.content) == {"error": "S3 connection failed"}

    def test_s3_exception_returns_500(self, mock_secrets: dict[str, str]) -> None:
        """When generate_presigned_url raises, return 500 with error message."""
        handler = ExternalDocumentsAPI.__new__(ExternalDocumentsAPI)
        handler.secrets = {**mock_secrets, "S3_PREFIX": ""}
        handler.request = MagicMock(path_params={"s3_key": "doc.pdf"})

        mock_s3_instance = MagicMock()
        mock_s3_instance.is_ready.return_value = True
        mock_s3_instance.generate_presigned_url.side_effect = Exception("AWS timeout")

        with patch("external_documents_viewer.applications.external_documents_api.S3") as mock_s3_class:
            with patch(
                "external_documents_viewer.applications.external_documents_api.S3Credentials"
            ) as mock_creds_class:
                mock_creds_class.return_value = MagicMock()
                mock_s3_class.return_value = mock_s3_instance

                effects = handler.get_document_url()

                assert mock_s3_instance.mock_calls == [
                    call.is_ready(),
                    call.generate_presigned_url("doc.pdf", expiration=3600),
                ]
                assert len(effects) == 1
                response = effects[0]
                assert isinstance(response, JSONResponse)
                assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
                assert json.loads(response.content) == {"error": "AWS timeout"}
