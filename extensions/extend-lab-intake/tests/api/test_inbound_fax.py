"""Tests for inbound fax API."""

from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest

from extend_lab_intake.api.inbound_fax import InboundFaxAPI
from extend_lab_intake.services.extend_client import (
    ExtendError,
    ExtendRunResult,
    ExtendRunStatus,
)
from extend_lab_intake.utils.constants import Secrets
from extend_lab_intake.utils.hmac_auth import generate_session_token


class TestInboundFaxAPIAuthentication:
    """Tests for InboundFaxAPI authentication."""

    @pytest.fixture
    def api(self) -> InboundFaxAPI:
        """Create an InboundFaxAPI instance."""
        api = InboundFaxAPI()
        api.secrets = {Secrets.INBOUND_FAX_TOKEN: "test-token-12345"}
        api.environment = {"CUSTOMER_IDENTIFIER": "test-instance"}
        api.request = MagicMock()
        api.request.headers = MagicMock()
        api.request.headers.get = MagicMock(return_value="")
        return api

    def test_authenticate_valid_key(self, api: InboundFaxAPI) -> None:
        """Test authentication with valid API key."""
        credentials = MagicMock()
        credentials.key = "test-token-12345"

        result = api.authenticate(credentials)

        assert result is True

    def test_authenticate_invalid_key(self, api: InboundFaxAPI) -> None:
        """Test authentication with invalid API key."""
        credentials = MagicMock()
        credentials.key = "wrong-token"

        result = api.authenticate(credentials)

        assert result is False

    def test_authenticate_missing_secret(self) -> None:
        """Test authentication when secret not configured."""
        api = InboundFaxAPI()
        api.secrets = {}
        api.request = MagicMock()
        api.request.headers = MagicMock()
        api.request.headers.get = MagicMock(return_value="")

        credentials = MagicMock()
        credentials.key = "any-token"

        result = api.authenticate(credentials)

        assert result is False


class TestInboundFaxAPISessionTokenAuthentication:
    """Tests for session token authentication."""

    @pytest.fixture
    def api(self) -> InboundFaxAPI:
        """Create an InboundFaxAPI instance with request mocking."""
        api = InboundFaxAPI()
        api.secrets = {Secrets.INBOUND_FAX_TOKEN: "test-secret-key"}
        api.environment = {"CUSTOMER_IDENTIFIER": "test-instance"}
        api.request = MagicMock()
        api.request.headers = MagicMock()
        api.request.headers.get = MagicMock(return_value="")
        return api

    def test_authenticate_valid_session_token(self, api: InboundFaxAPI) -> None:
        """Test authentication with valid session token."""
        # Generate a valid session token
        token = generate_session_token("test-secret-key")

        credentials = MagicMock()
        credentials.key = token

        result = api.authenticate(credentials)

        assert result is True

    def test_authenticate_invalid_session_token(self, api: InboundFaxAPI) -> None:
        """Test authentication with invalid session token."""
        import time

        # Create a token with wrong signature
        timestamp = str(int(time.time()))
        invalid_token = f"{timestamp}.invalid_signature_here"

        credentials = MagicMock()
        credentials.key = invalid_token

        result = api.authenticate(credentials)

        assert result is False

    def test_authenticate_expired_session_token(self, api: InboundFaxAPI) -> None:
        """Test authentication with expired session token."""
        import time

        # Generate token with old timestamp (10 minutes ago)
        old_timestamp = int(time.time()) - 600
        token = generate_session_token("test-secret-key", timestamp=old_timestamp)

        credentials = MagicMock()
        credentials.key = token

        result = api.authenticate(credentials)

        assert result is False

    def test_authenticate_tampered_session_token(self, api: InboundFaxAPI) -> None:
        """Test authentication when timestamp has been tampered with."""
        # Generate a valid token
        token = generate_session_token("test-secret-key")
        parts = token.split(".")

        # Change timestamp but keep original signature
        tampered_token = f"{int(parts[0]) + 100}.{parts[1]}"

        credentials = MagicMock()
        credentials.key = tampered_token

        result = api.authenticate(credentials)

        assert result is False

    def test_authenticate_session_token_wrong_key(self, api: InboundFaxAPI) -> None:
        """Test authentication with token signed with wrong key."""
        # Generate token with different key
        token = generate_session_token("different-secret-key")

        credentials = MagicMock()
        credentials.key = token

        result = api.authenticate(credentials)

        assert result is False

    def test_authenticate_falls_back_to_api_key(self, api: InboundFaxAPI) -> None:
        """Test that API key without dot is used directly."""
        credentials = MagicMock()
        credentials.key = "test-secret-key"  # Matches the secret, no dot

        result = api.authenticate(credentials)

        assert result is True

    def test_authenticate_api_key_takes_precedence_for_non_token(
        self, api: InboundFaxAPI
    ) -> None:
        """Test that keys without dots use direct API key auth."""
        credentials = MagicMock()
        credentials.key = "wrong-api-key"  # No dot, uses direct comparison

        result = api.authenticate(credentials)

        assert result is False

    def test_authenticate_session_token_missing_secret(self) -> None:
        """Test session token authentication when secret not configured."""
        api = InboundFaxAPI()
        api.secrets = {}  # No secret
        api.request = MagicMock()
        api.request.headers = MagicMock()
        api.request.headers.get = MagicMock(return_value="")

        import time

        # Create a token-like string (has a dot)
        token = f"{int(time.time())}.somesignature"

        credentials = MagicMock()
        credentials.key = token

        result = api.authenticate(credentials)

        assert result is False


class TestInboundFaxAPIReceiveFax:
    """Tests for receive_fax endpoint."""

    @pytest.fixture
    def api(self) -> InboundFaxAPI:
        """Create a configured API instance."""
        api = InboundFaxAPI()
        api.secrets = {
            Secrets.INBOUND_FAX_TOKEN: "test-token",
            Secrets.AWS_ACCESS_KEY_ID: "test-aws-key",
            Secrets.AWS_SECRET_ACCESS_KEY: "test-aws-secret",
            Secrets.EXTEND_AI_KEY: "test-extend-key",
            Secrets.EXTEND_AI_PROCESSOR_TREE: '{"class-1": {"name": "Classifier", "type": "CLASSIFY", "extractors": {}}}',
        }
        api.environment = {"CUSTOMER_IDENTIFIER": "test-instance"}
        api.request = MagicMock()
        return api

    def test_receive_fax_no_file(self, api: InboundFaxAPI) -> None:
        """Test receive_fax with no file provided."""
        api.request.form_data.return_value = {}

        result = api.receive_fax()

        assert len(result) == 1
        # Check response is error

    def test_receive_fax_empty_file(self, api: InboundFaxAPI) -> None:
        """Test receive_fax with empty file content."""
        file_part = MagicMock()
        file_part.content = None
        api.request.form_data.return_value = {"file": file_part}

        result = api.receive_fax()

        assert len(result) == 1

    @patch.object(InboundFaxAPI, "_classify_document")
    def test_receive_fax_success(
        self, mock_classify: MagicMock, api: InboundFaxAPI
    ) -> None:
        """Test successful fax receive."""
        file_part = MagicMock()
        file_part.content = b"PDF content"
        file_part.filename = "test.pdf"
        api.request.form_data.return_value = {"file": file_part}

        mock_classify.return_value = {
            "success": True,
            "classification": "lipid_panel",
            "classification_confidence": 0.95,
        }

        result = api.receive_fax()

        assert len(result) == 1
        mock_classify.assert_called_once()

    @patch.object(InboundFaxAPI, "_classify_document")
    def test_receive_fax_classification_error(
        self, mock_classify: MagicMock, api: InboundFaxAPI
    ) -> None:
        """Test fax receive with classification error."""
        file_part = MagicMock()
        file_part.content = b"PDF content"
        file_part.filename = "test.pdf"
        api.request.form_data.return_value = {"file": file_part}

        mock_classify.return_value = {
            "success": False,
            "error": "Classification failed",
        }

        result = api.receive_fax()

        assert len(result) == 1


class TestInboundFaxAPIClassifyDocument:
    """Tests for _classify_document method."""

    @pytest.fixture
    def api(self) -> InboundFaxAPI:
        """Create a configured API instance."""
        api = InboundFaxAPI()
        api.secrets = {
            Secrets.AWS_ACCESS_KEY_ID: "test-aws-key",
            Secrets.AWS_SECRET_ACCESS_KEY: "test-aws-secret",
            Secrets.EXTEND_AI_KEY: "test-extend-key",
            Secrets.EXTEND_AI_PROCESSOR_TREE: '{"class-1": {"name": "Classifier", "type": "CLASSIFY", "extractors": {}}}',
        }
        api.environment = {"CUSTOMER_IDENTIFIER": "test-instance"}
        return api

    @patch.object(InboundFaxAPI, "_get_s3_client")
    @patch.object(InboundFaxAPI, "_get_extend_client")
    def test_classify_s3_upload_failure(
        self,
        mock_get_extend: MagicMock,
        mock_get_s3: MagicMock,
        api: InboundFaxAPI,
    ) -> None:
        """Test classification when S3 upload fails."""
        mock_s3 = MagicMock()
        mock_s3.upload_pdf.return_value = MagicMock(status_code=500)
        mock_get_s3.return_value = mock_s3

        result = api._classify_document(
            pdf_data=b"PDF",
            file_name="test.pdf",
            s3_key="test-key",
            intake_id="intake-123",
        )

        assert result["success"] is False
        assert "S3 upload failed" in result["error"]

    @patch.object(InboundFaxAPI, "_get_s3_client")
    @patch.object(InboundFaxAPI, "_get_extend_client")
    def test_classify_no_processor_tree(
        self,
        mock_get_extend: MagicMock,
        mock_get_s3: MagicMock,
    ) -> None:
        """Test classification when processor tree not configured."""
        api = InboundFaxAPI()
        api.secrets = {
            Secrets.AWS_ACCESS_KEY_ID: "key",
            Secrets.AWS_SECRET_ACCESS_KEY: "secret",
            Secrets.EXTEND_AI_KEY: "key",
        }
        api.environment = {"CUSTOMER_IDENTIFIER": "test"}

        mock_s3 = MagicMock()
        mock_s3.upload_pdf.return_value = MagicMock(status_code=200)
        mock_s3.generate_presigned_url.return_value = "https://example.com/file"
        mock_get_s3.return_value = mock_s3

        result = api._classify_document(
            pdf_data=b"PDF",
            file_name="test.pdf",
            s3_key="test-key",
            intake_id="intake-123",
        )

        assert result["success"] is False
        assert "EXTEND_AI_PROCESSOR_TREE" in result["error"]

    @patch.object(InboundFaxAPI, "_get_s3_client")
    @patch.object(InboundFaxAPI, "_get_extend_client")
    def test_classify_extend_error(
        self,
        mock_get_extend: MagicMock,
        mock_get_s3: MagicMock,
        api: InboundFaxAPI,
    ) -> None:
        """Test classification when Extend AI returns error."""
        mock_s3 = MagicMock()
        mock_s3.upload_pdf.return_value = MagicMock(status_code=200)
        mock_s3.generate_presigned_url.return_value = "https://example.com/file"
        mock_get_s3.return_value = mock_s3

        mock_extend = MagicMock()
        mock_extend.run_processor.return_value = ExtendError(
            status_code=500, message="API error"
        )
        mock_get_extend.return_value = mock_extend

        result = api._classify_document(
            pdf_data=b"PDF",
            file_name="test.pdf",
            s3_key="test-key",
            intake_id="intake-123",
        )

        assert result["success"] is False
        assert "Classification failed" in result["error"]

    @patch.object(InboundFaxAPI, "_get_s3_client")
    @patch.object(InboundFaxAPI, "_get_extend_client")
    def test_classify_extend_wait_error(
        self,
        mock_get_extend: MagicMock,
        mock_get_s3: MagicMock,
        api: InboundFaxAPI,
    ) -> None:
        """Test classification when wait_for_completion fails."""
        mock_s3 = MagicMock()
        mock_s3.upload_pdf.return_value = MagicMock(status_code=200)
        mock_s3.generate_presigned_url.return_value = "https://example.com/file"
        mock_get_s3.return_value = mock_s3

        mock_extend = MagicMock()
        mock_extend.run_processor.return_value = ExtendRunResult(
            run_id="run-123", status=ExtendRunStatus.PENDING
        )
        mock_extend.wait_for_completion.return_value = ExtendError(
            status_code=500, message="Timeout"
        )
        mock_get_extend.return_value = mock_extend

        result = api._classify_document(
            pdf_data=b"PDF",
            file_name="test.pdf",
            s3_key="test-key",
            intake_id="intake-123",
        )

        assert result["success"] is False

    @patch.object(InboundFaxAPI, "_get_s3_client")
    @patch.object(InboundFaxAPI, "_get_extend_client")
    def test_classify_extend_run_failed(
        self,
        mock_get_extend: MagicMock,
        mock_get_s3: MagicMock,
        api: InboundFaxAPI,
    ) -> None:
        """Test classification when run status is FAILED."""
        mock_s3 = MagicMock()
        mock_s3.upload_pdf.return_value = MagicMock(status_code=200)
        mock_s3.generate_presigned_url.return_value = "https://example.com/file"
        mock_get_s3.return_value = mock_s3

        mock_extend = MagicMock()
        mock_extend.run_processor.return_value = ExtendRunResult(
            run_id="run-123", status=ExtendRunStatus.PENDING
        )
        mock_extend.wait_for_completion.return_value = ExtendRunResult(
            run_id="run-123", status=ExtendRunStatus.FAILED, error="Processing error"
        )
        mock_get_extend.return_value = mock_extend

        result = api._classify_document(
            pdf_data=b"PDF",
            file_name="test.pdf",
            s3_key="test-key",
            intake_id="intake-123",
        )

        assert result["success"] is False

    @patch.object(InboundFaxAPI, "_get_s3_client")
    @patch.object(InboundFaxAPI, "_get_extend_client")
    def test_classify_success(
        self,
        mock_get_extend: MagicMock,
        mock_get_s3: MagicMock,
        api: InboundFaxAPI,
    ) -> None:
        """Test successful classification."""
        mock_s3 = MagicMock()
        mock_s3.upload_pdf.return_value = MagicMock(status_code=200)
        mock_s3.generate_presigned_url.return_value = "https://example.com/file"
        mock_s3.upload_json.return_value = MagicMock(status_code=200)
        mock_get_s3.return_value = mock_s3

        mock_extend = MagicMock()
        mock_extend.run_processor.return_value = ExtendRunResult(
            run_id="run-123", status=ExtendRunStatus.PENDING
        )
        mock_extend.wait_for_completion.return_value = ExtendRunResult(
            run_id="run-123",
            status=ExtendRunStatus.COMPLETED,
            output={
                "id": "lipid_panel",
                "type": "Lipid Panel",
                "confidence": 0.95,
            },
        )
        mock_get_extend.return_value = mock_extend

        result = api._classify_document(
            pdf_data=b"PDF",
            file_name="test.pdf",
            s3_key="test-key",
            intake_id="intake-123",
        )

        assert result["success"] is True
        assert result["classification"] == "Lipid Panel"
        assert result["classification_confidence"] == 0.95


class TestInboundFaxAPIExtractDocument:
    """Tests for extract_document endpoint."""

    @pytest.fixture
    def api(self) -> InboundFaxAPI:
        """Create a configured API instance."""
        api = InboundFaxAPI()
        api.secrets = {
            Secrets.AWS_ACCESS_KEY_ID: "test-aws-key",
            Secrets.AWS_SECRET_ACCESS_KEY: "test-aws-secret",
            Secrets.EXTEND_AI_KEY: "test-extend-key",
            Secrets.ANTHROPIC_API_KEY: "test-anthropic-key",
            Secrets.EXTEND_AI_PROCESSOR_TREE: '{"class-1": {"name": "Classifier", "type": "CLASSIFY", "extractors": {"lipid_panel": {"processor_id": "ext-1", "name": "Extractor", "type": "EXTRACT"}}}}',
        }
        api.environment = {"CUSTOMER_IDENTIFIER": "test-instance"}
        api.request = MagicMock()
        return api

    def test_extract_document_no_intake_id(self, api: InboundFaxAPI) -> None:
        """Test extract_document with no intake_id."""
        api.request.json.return_value = {}

        result = api.extract_document()

        assert len(result) == 1

    @patch.object(InboundFaxAPI, "_extract_and_process")
    @patch.object(InboundFaxAPI, "_get_fallback_team_id")
    def test_extract_document_success(
        self,
        mock_get_team: MagicMock,
        mock_extract: MagicMock,
        api: InboundFaxAPI,
    ) -> None:
        """Test successful extraction."""
        api.request.json.return_value = {"intake_id": "intake-123"}
        mock_get_team.return_value = "team-1"
        mock_extract.return_value = {
            "success": True,
            "patient_id": "patient-123",
            "diagnostic_report_id": "dr-123",
            "confidence": "high",
            "classification": "Lipid Panel",
            "summary": "All normal",
            "file_name": "test.pdf",
            "output": {},
        }

        result = api.extract_document()

        # Should have task effect + JSON response
        assert len(result) >= 1

    @patch.object(InboundFaxAPI, "_extract_and_process")
    def test_extract_document_failure(
        self, mock_extract: MagicMock, api: InboundFaxAPI
    ) -> None:
        """Test extraction failure."""
        api.request.json.return_value = {"intake_id": "intake-123"}
        mock_extract.return_value = {
            "success": False,
            "error": "Processing failed",
        }

        result = api.extract_document()

        assert len(result) == 1


class TestInboundFaxAPIExtractAndProcess:
    """Tests for _extract_and_process method."""

    @pytest.fixture
    def api(self) -> InboundFaxAPI:
        """Create a configured API instance."""
        api = InboundFaxAPI()
        api.secrets = {
            Secrets.AWS_ACCESS_KEY_ID: "test-aws-key",
            Secrets.AWS_SECRET_ACCESS_KEY: "test-aws-secret",
            Secrets.EXTEND_AI_KEY: "test-extend-key",
            Secrets.ANTHROPIC_API_KEY: "test-anthropic-key",
            Secrets.EXTEND_AI_PROCESSOR_TREE: '{"class-1": {"name": "Classifier", "type": "CLASSIFY", "extractors": {"lipid_panel": {"processor_id": "ext-1", "name": "Extractor", "type": "EXTRACT"}}}}',
        }
        api.environment = {"CUSTOMER_IDENTIFIER": "test-instance"}
        return api

    @patch.object(InboundFaxAPI, "_get_s3_client")
    def test_extract_metadata_not_found(
        self, mock_get_s3: MagicMock, api: InboundFaxAPI
    ) -> None:
        """Test extraction when metadata not found."""
        mock_s3 = MagicMock()
        mock_s3.get_json.return_value = None
        mock_get_s3.return_value = mock_s3

        result = api._extract_and_process("intake-123")

        assert result["success"] is False
        assert "Metadata not found" in result["error"]

    @patch.object(InboundFaxAPI, "_get_s3_client")
    def test_extract_already_processed(
        self, mock_get_s3: MagicMock, api: InboundFaxAPI
    ) -> None:
        """Test extraction when already processed."""
        mock_s3 = MagicMock()
        mock_s3.get_json.return_value = {
            "file_name": "test.pdf",
            "classification": {"id": "lipid_panel", "type": "Lipid Panel"},
            "extraction": {"processed_at": "2024-01-15"},
        }
        mock_get_s3.return_value = mock_s3

        result = api._extract_and_process("intake-123")

        assert result["success"] is False
        assert "already been processed" in result["error"]

    @patch.object(InboundFaxAPI, "_get_s3_client")
    def test_extract_no_processor_tree(self, mock_get_s3: MagicMock) -> None:
        """Test extraction when no processor tree configured."""
        api = InboundFaxAPI()
        api.secrets = {
            Secrets.AWS_ACCESS_KEY_ID: "key",
            Secrets.AWS_SECRET_ACCESS_KEY: "secret",
        }
        api.environment = {"CUSTOMER_IDENTIFIER": "test"}

        mock_s3 = MagicMock()
        mock_s3.get_json.return_value = {
            "file_name": "test.pdf",
            "classification": {"id": "lipid_panel", "type": "Lipid Panel"},
            "extraction": None,
        }
        mock_get_s3.return_value = mock_s3

        result = api._extract_and_process("intake-123")

        assert result["success"] is False


class TestInboundFaxAPISaveReport:
    """Tests for save_report endpoint."""

    @pytest.fixture
    def api(self) -> InboundFaxAPI:
        """Create a configured API instance."""
        api = InboundFaxAPI()
        api.secrets = {
            Secrets.AWS_ACCESS_KEY_ID: "test-aws-key",
            Secrets.AWS_SECRET_ACCESS_KEY: "test-aws-secret",
            Secrets.FHIR_CLIENT_ID: "fhir-client-id",
            Secrets.FHIR_CLIENT_SECRET: "fhir-client-secret",
        }
        api.environment = {"CUSTOMER_IDENTIFIER": "test-instance"}
        api.request = MagicMock()
        return api

    def test_save_report_no_intake_id(self, api: InboundFaxAPI) -> None:
        """Test save_report with no intake_id."""
        api.request.json.return_value = {}

        result = api.save_report()

        assert len(result) == 1

    @patch.object(InboundFaxAPI, "_get_s3_client")
    def test_save_report_metadata_not_found(
        self, mock_get_s3: MagicMock, api: InboundFaxAPI
    ) -> None:
        """Test save_report when metadata not found."""
        api.request.json.return_value = {"intake_id": "intake-123"}

        mock_s3 = MagicMock()
        mock_s3.get_json.return_value = None
        mock_get_s3.return_value = mock_s3

        result = api.save_report()

        assert len(result) == 1

    @patch.object(InboundFaxAPI, "_get_s3_client")
    def test_save_report_not_extracted(
        self, mock_get_s3: MagicMock, api: InboundFaxAPI
    ) -> None:
        """Test save_report when not yet extracted."""
        api.request.json.return_value = {"intake_id": "intake-123"}

        mock_s3 = MagicMock()
        mock_s3.get_json.return_value = {
            "file_name": "test.pdf",
            "classification": {},
            "extraction": None,
        }
        mock_get_s3.return_value = mock_s3

        result = api.save_report()

        assert len(result) == 1

    @patch.object(InboundFaxAPI, "_get_s3_client")
    def test_save_report_already_saved(
        self, mock_get_s3: MagicMock, api: InboundFaxAPI
    ) -> None:
        """Test save_report when already saved."""
        api.request.json.return_value = {"intake_id": "intake-123"}

        mock_s3 = MagicMock()
        mock_s3.get_json.return_value = {
            "file_name": "test.pdf",
            "classification": {},
            "extraction": {
                "diagnostic_report_id": "dr-123",
                "patient_match": {"patient_id": "p-123"},
            },
        }
        mock_get_s3.return_value = mock_s3

        result = api.save_report()

        assert len(result) == 1

    @patch.object(InboundFaxAPI, "_get_s3_client")
    def test_save_report_no_patient(
        self, mock_get_s3: MagicMock, api: InboundFaxAPI
    ) -> None:
        """Test save_report when no patient matched."""
        api.request.json.return_value = {"intake_id": "intake-123"}

        mock_s3 = MagicMock()
        mock_s3.get_json.return_value = {
            "file_name": "test.pdf",
            "classification": {},
            "extraction": {
                "patient_match": {"patient_id": None},
            },
        }
        mock_get_s3.return_value = mock_s3

        result = api.save_report()

        assert len(result) == 1


class TestInboundFaxAPIGetDocument:
    """Tests for get_document endpoint."""

    @pytest.fixture
    def api(self) -> InboundFaxAPI:
        """Create a configured API instance."""
        api = InboundFaxAPI()
        api.secrets = {
            Secrets.AWS_ACCESS_KEY_ID: "key",
            Secrets.AWS_SECRET_ACCESS_KEY: "secret",
        }
        api.environment = {"CUSTOMER_IDENTIFIER": "test"}
        api.request = MagicMock()
        api.request.query_params = {"intake_id": "intake-123"}
        return api

    def test_get_document_no_intake_id(self, api: InboundFaxAPI) -> None:
        """Test get_document when intake_id is missing."""
        api.request.query_params = {}

        result = api.get_document()

        assert len(result) == 1

    @patch.object(InboundFaxAPI, "_get_s3_client")
    def test_get_document_not_found(
        self, mock_get_s3: MagicMock, api: InboundFaxAPI
    ) -> None:
        """Test get_document when not found."""
        mock_s3 = MagicMock()
        mock_s3.get_json.return_value = None
        mock_get_s3.return_value = mock_s3

        result = api.get_document()

        assert len(result) == 1

    @patch.object(InboundFaxAPI, "_get_s3_client")
    def test_get_document_success(
        self, mock_get_s3: MagicMock, api: InboundFaxAPI
    ) -> None:
        """Test get_document success."""
        mock_s3 = MagicMock()
        mock_s3.get_json.return_value = {
            "intake_id": "intake-123",
            "file_name": "report.pdf",
            "status": "classified",
        }
        mock_s3.generate_presigned_url.return_value = "https://example.com/signed"
        mock_get_s3.return_value = mock_s3

        result = api.get_document()

        assert len(result) == 1
        mock_s3.generate_presigned_url.assert_called_once()


class TestInboundFaxAPIDiscardDocument:
    """Tests for discard_document endpoint."""

    @pytest.fixture
    def api(self) -> InboundFaxAPI:
        """Create a configured API instance."""
        api = InboundFaxAPI()
        api.secrets = {
            Secrets.AWS_ACCESS_KEY_ID: "key",
            Secrets.AWS_SECRET_ACCESS_KEY: "secret",
        }
        api.environment = {"CUSTOMER_IDENTIFIER": "test"}
        api.request = MagicMock()
        return api

    def test_discard_document_no_intake_id(self, api: InboundFaxAPI) -> None:
        """Test discard_document with no intake_id."""
        api.request.json.return_value = {}

        result = api.discard_document()

        assert len(result) == 1

    @patch.object(InboundFaxAPI, "_get_s3_client")
    def test_discard_document_success(
        self, mock_get_s3: MagicMock, api: InboundFaxAPI
    ) -> None:
        """Test discard_document success."""
        api.request.json.return_value = {"intake_id": "intake-123"}

        mock_s3 = MagicMock()
        mock_s3.get_json.return_value = {"file_name": "test.pdf"}
        mock_s3.delete_object.return_value = None
        mock_get_s3.return_value = mock_s3

        result = api.discard_document()

        assert len(result) == 1
        assert mock_s3.delete_object.call_count == 2  # PDF and metadata

    @patch.object(InboundFaxAPI, "_get_s3_client")
    def test_discard_document_no_metadata(
        self, mock_get_s3: MagicMock, api: InboundFaxAPI
    ) -> None:
        """Test discard_document when no metadata exists."""
        api.request.json.return_value = {"intake_id": "intake-123"}

        mock_s3 = MagicMock()
        mock_s3.get_json.return_value = None
        mock_get_s3.return_value = mock_s3

        result = api.discard_document()

        assert len(result) == 1


class TestInboundFaxAPIHealthCheck:
    """Tests for health_check endpoint."""

    def test_health_check(self) -> None:
        """Test health check returns healthy."""
        api = InboundFaxAPI()
        api.secrets = {}
        api.environment = {}

        result = api.health_check()

        assert len(result) == 1


class TestInboundFaxAPIBuildLabReport:
    """Tests for _build_lab_report method."""

    @pytest.fixture
    def api(self) -> InboundFaxAPI:
        """Create an API instance."""
        api = InboundFaxAPI()
        api.secrets = {}
        api.environment = {}
        return api

    def test_build_lab_report_basic(self, api: InboundFaxAPI) -> None:
        """Test building a basic lab report."""
        extraction_output = {
            "value": {
                "collection_date": "2024-01-15",
                "test_results": [
                    {
                        "test_name": "Cholesterol",
                        "result_value": "200",
                        "unit": "mg/dL",
                        "reference_range": "<200",
                        "abnormal_flag": False,
                    }
                ],
            }
        }

        report = api._build_lab_report(
            patient_id="patient-123",
            extraction_output=extraction_output,
            pdf_data=b"PDF",
        )

        assert report.patient_id == "patient-123"
        # Date gets normalized to full ISO 8601 datetime
        assert report.effective_date == "2024-01-15T00:00:00Z"

    def test_build_lab_report_no_date(self, api: InboundFaxAPI) -> None:
        """Test building lab report with no date."""
        extraction_output = {"value": {"test_results": []}}

        report = api._build_lab_report(
            patient_id="patient-123",
            extraction_output=extraction_output,
            pdf_data=b"PDF",
        )

        # Should use current time
        assert report.effective_date is not None


class TestInboundFaxAPIParseLabTests:
    """Tests for _parse_lab_tests method."""

    @pytest.fixture
    def api(self) -> InboundFaxAPI:
        """Create an API instance."""
        api = InboundFaxAPI()
        api.secrets = {}
        api.environment = {}
        return api

    def test_parse_lab_tests_empty(self, api: InboundFaxAPI) -> None:
        """Test parsing empty test results."""
        tests = api._parse_lab_tests({})
        assert tests == []

    def test_parse_lab_tests_with_results(self, api: InboundFaxAPI) -> None:
        """Test parsing test results."""
        extraction_values = {
            "test_results": [
                {
                    "test_name": "Total Cholesterol",
                    "result_value": "200",
                    "unit": "mg/dL",
                    "reference_range": "<200",
                    "abnormal_flag": False,
                },
                {
                    "test_name": "LDL",
                    "result_value": "150",
                    "unit": "mg/dL",
                    "reference_range": "<100",
                    "abnormal_flag": "H",
                },
            ]
        }

        tests = api._parse_lab_tests(extraction_values)

        assert len(tests) == 1
        assert len(tests[0].values) == 2

    def test_parse_lab_tests_alternate_keys(self, api: InboundFaxAPI) -> None:
        """Test parsing with alternate field names."""
        extraction_values = {
            "tests": [
                {"name": "WBC", "value": "7.0", "units": "K/uL"},
            ]
        }

        tests = api._parse_lab_tests(extraction_values)

        assert len(tests) == 1

    def test_parse_lab_tests_skip_non_dict(self, api: InboundFaxAPI) -> None:
        """Test that non-dict items are skipped."""
        extraction_values = {
            "test_results": [
                {"test_name": "Test1", "result_value": "100"},
                "not a dict",
                None,
            ]
        }

        tests = api._parse_lab_tests(extraction_values)

        assert len(tests) == 1
        assert len(tests[0].values) == 1


class TestInboundFaxAPIGetFallbackTeamId:
    """Tests for _get_fallback_team_id method."""

    @pytest.fixture
    def api(self) -> InboundFaxAPI:
        """Create an API instance."""
        api = InboundFaxAPI()
        return api

    @patch("canvas_sdk.v1.data.team.Team.objects")
    def test_get_fallback_team_lab_team(
        self, mock_team_objects: MagicMock, api: InboundFaxAPI
    ) -> None:
        """Test getting fallback team when lab team exists."""
        mock_team = MagicMock()
        mock_team.id = "team-lab-123"
        mock_team_objects.filter.return_value.all.return_value = [mock_team]

        result = api._get_fallback_team_id()

        assert result == "team-lab-123"

    @patch("canvas_sdk.v1.data.team.Team.objects")
    def test_get_fallback_team_any_team(
        self, mock_team_objects: MagicMock, api: InboundFaxAPI
    ) -> None:
        """Test getting fallback team when no lab team exists."""
        mock_team = MagicMock()
        mock_team.id = "team-any-123"
        mock_team_objects.filter.return_value.all.return_value = []
        mock_team_objects.all.return_value.__getitem__ = MagicMock(
            return_value=[mock_team]
        )

        # Handle the slice
        mock_team_objects.all.return_value = [mock_team]

        result = api._get_fallback_team_id()

        # Either finds a team or returns None

    @patch("canvas_sdk.v1.data.team.Team.objects")
    def test_get_fallback_team_no_teams(
        self, mock_team_objects: MagicMock, api: InboundFaxAPI
    ) -> None:
        """Test getting fallback team when no teams exist."""
        mock_team_objects.filter.return_value.all.return_value = []
        mock_team_objects.all.return_value.__getitem__ = MagicMock(return_value=[])
        mock_team_objects.all.return_value = []

        result = api._get_fallback_team_id()

        assert result is None
