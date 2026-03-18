"""Tests for Extend AI client."""

from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest

from extend_lab_intake.services.extend_client import (
    ClassificationResult,
    DocumentProcessor,
    ExtendClient,
    ExtendError,
    ExtendRunResult,
    ExtendRunStatus,
    ProcessorNode,
    ProcessorTree,
    ProcessorType,
)


class TestExtendRunResult:
    """Tests for ExtendRunResult."""

    def test_from_dict_basic(self) -> None:
        """Test creating ExtendRunResult from dict."""
        data = {
            "id": "run-123",
            "status": "COMPLETED",
            "output": {"key": "value"},
            "error": None,
        }
        result = ExtendRunResult.from_dict(data)

        assert result.run_id == "run-123"
        assert result.status == ExtendRunStatus.COMPLETED
        assert result.output == {"key": "value"}
        assert result.error is None

    def test_from_dict_with_error(self) -> None:
        """Test creating ExtendRunResult with error."""
        data = {
            "id": "run-456",
            "status": "FAILED",
            "output": None,
            "error": "Processing failed",
        }
        result = ExtendRunResult.from_dict(data)

        assert result.run_id == "run-456"
        assert result.status == ExtendRunStatus.FAILED
        assert result.error == "Processing failed"

    def test_from_dict_defaults(self) -> None:
        """Test default values when dict is sparse."""
        data = {}
        result = ExtendRunResult.from_dict(data)

        assert result.run_id == ""
        assert result.status == ExtendRunStatus.PENDING


class TestExtendError:
    """Tests for ExtendError."""

    def test_error_creation(self) -> None:
        """Test creating an ExtendError."""
        error = ExtendError(status_code=400, message="Bad request")

        assert error.status_code == 400
        assert error.message == "Bad request"


class TestExtendClient:
    """Tests for ExtendClient."""

    @pytest.fixture
    def client(self) -> ExtendClient:
        """Create an ExtendClient instance."""
        return ExtendClient(api_key="test-api-key")

    def test_initialization(self, client: ExtendClient) -> None:
        """Test client initialization."""
        assert client.api_key == "test-api-key"
        assert "Authorization" in client.headers
        assert client.headers["Authorization"] == "Bearer test-api-key"
        assert "x-extend-api-version" in client.headers

    @patch("requests.post")
    def test_run_processor_success(
        self, mock_post: MagicMock, client: ExtendClient
    ) -> None:
        """Test successful processor run."""
        mock_post.return_value = MagicMock(
            status_code=HTTPStatus.OK,
            json=lambda: {
                "success": True,
                "processorRun": {
                    "id": "run-123",
                    "status": "PENDING",
                },
            },
        )

        result = client.run_processor(
            processor_id="proc-123",
            file_name="test.pdf",
            file_url="https://example.com/test.pdf",
        )

        assert isinstance(result, ExtendRunResult)
        assert result.run_id == "run-123"
        mock_post.assert_called_once()

    @patch("requests.post")
    def test_run_processor_with_config(
        self, mock_post: MagicMock, client: ExtendClient
    ) -> None:
        """Test processor run with config override."""
        mock_post.return_value = MagicMock(
            status_code=HTTPStatus.OK,
            json=lambda: {
                "success": True,
                "processorRun": {"id": "run-123", "status": "PENDING"},
            },
        )

        result = client.run_processor(
            processor_id="proc-123",
            file_name="test.pdf",
            file_url="https://example.com/test.pdf",
            config={"custom": "config"},
        )

        assert isinstance(result, ExtendRunResult)
        call_args = mock_post.call_args
        assert call_args.kwargs["json"]["config"] == {"custom": "config"}

    @patch("requests.post")
    def test_run_processor_failure(
        self, mock_post: MagicMock, client: ExtendClient
    ) -> None:
        """Test processor run failure."""
        mock_post.return_value = MagicMock(
            status_code=HTTPStatus.BAD_REQUEST,
            content=b"Invalid processor ID",
        )

        result = client.run_processor(
            processor_id="invalid",
            file_name="test.pdf",
            file_url="https://example.com/test.pdf",
        )

        assert isinstance(result, ExtendError)
        assert result.status_code == HTTPStatus.BAD_REQUEST
        assert "Invalid processor ID" in result.message

    @patch("requests.post")
    def test_run_processor_success_false(
        self, mock_post: MagicMock, client: ExtendClient
    ) -> None:
        """Test processor run when success=false in response."""
        mock_post.return_value = MagicMock(
            status_code=HTTPStatus.OK,
            json=lambda: {"success": False},
            content=b"Operation failed",
        )

        result = client.run_processor(
            processor_id="proc-123",
            file_name="test.pdf",
            file_url="https://example.com/test.pdf",
        )

        assert isinstance(result, ExtendError)

    @patch("requests.get")
    def test_get_run_status_success(
        self, mock_get: MagicMock, client: ExtendClient
    ) -> None:
        """Test getting processor run status."""
        mock_get.return_value = MagicMock(
            status_code=HTTPStatus.OK,
            json=lambda: {
                "success": True,
                "processorRun": {
                    "id": "run-123",
                    "status": "COMPLETED",
                    "output": {"result": "data"},
                },
            },
        )

        result = client.get_run_status("run-123")

        assert isinstance(result, ExtendRunResult)
        assert result.status == ExtendRunStatus.COMPLETED
        assert result.output == {"result": "data"}

    @patch("requests.get")
    def test_get_run_status_failure(
        self, mock_get: MagicMock, client: ExtendClient
    ) -> None:
        """Test get run status failure."""
        mock_get.return_value = MagicMock(
            status_code=HTTPStatus.NOT_FOUND,
            content=b"Run not found",
        )

        result = client.get_run_status("invalid-run")

        assert isinstance(result, ExtendError)
        assert result.status_code == HTTPStatus.NOT_FOUND

    @patch("requests.get")
    def test_wait_for_completion_immediate(
        self, mock_get: MagicMock, client: ExtendClient
    ) -> None:
        """Test wait_for_completion when already completed."""
        mock_get.return_value = MagicMock(
            status_code=HTTPStatus.OK,
            json=lambda: {
                "success": True,
                "processorRun": {
                    "id": "run-123",
                    "status": "COMPLETED",
                    "output": {"data": "result"},
                },
            },
        )

        result = client.wait_for_completion("run-123")

        assert isinstance(result, ExtendRunResult)
        assert result.status == ExtendRunStatus.COMPLETED
        mock_get.assert_called_once()

    @patch("time.sleep")
    @patch("requests.get")
    def test_wait_for_completion_polling(
        self, mock_get: MagicMock, mock_sleep: MagicMock, client: ExtendClient
    ) -> None:
        """Test wait_for_completion with polling."""
        mock_get.side_effect = [
            MagicMock(
                status_code=HTTPStatus.OK,
                json=lambda: {
                    "success": True,
                    "processorRun": {"id": "run-123", "status": "PROCESSING"},
                },
            ),
            MagicMock(
                status_code=HTTPStatus.OK,
                json=lambda: {
                    "success": True,
                    "processorRun": {"id": "run-123", "status": "COMPLETED"},
                },
            ),
        ]

        result = client.wait_for_completion("run-123")

        assert isinstance(result, ExtendRunResult)
        assert result.status == ExtendRunStatus.COMPLETED
        assert mock_get.call_count == 2
        mock_sleep.assert_called_once()

    @patch("time.sleep")
    @patch("requests.get")
    def test_wait_for_completion_timeout(
        self, mock_get: MagicMock, mock_sleep: MagicMock, client: ExtendClient
    ) -> None:
        """Test wait_for_completion timeout."""
        mock_get.return_value = MagicMock(
            status_code=HTTPStatus.OK,
            json=lambda: {
                "success": True,
                "processorRun": {"id": "run-123", "status": "PROCESSING"},
            },
        )

        result = client.wait_for_completion("run-123", max_attempts=3)

        assert isinstance(result, ExtendError)
        assert result.status_code == HTTPStatus.REQUEST_TIMEOUT
        assert "did not complete within timeout" in result.message

    @patch("time.sleep")
    @patch("requests.get")
    def test_wait_for_completion_failed_status(
        self, mock_get: MagicMock, mock_sleep: MagicMock, client: ExtendClient
    ) -> None:
        """Test wait_for_completion when run fails."""
        mock_get.return_value = MagicMock(
            status_code=HTTPStatus.OK,
            json=lambda: {
                "success": True,
                "processorRun": {
                    "id": "run-123",
                    "status": "FAILED",
                    "error": "Processing error",
                },
            },
        )

        result = client.wait_for_completion("run-123")

        assert isinstance(result, ExtendRunResult)
        assert result.status == ExtendRunStatus.FAILED

    @patch("requests.get")
    def test_wait_for_completion_api_error(
        self, mock_get: MagicMock, client: ExtendClient
    ) -> None:
        """Test wait_for_completion with API error."""
        mock_get.return_value = MagicMock(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            content=b"Server error",
        )

        result = client.wait_for_completion("run-123")

        assert isinstance(result, ExtendError)

    @patch("requests.get")
    def test_list_processors_success(
        self, mock_get: MagicMock, client: ExtendClient
    ) -> None:
        """Test listing processors."""
        mock_get.return_value = MagicMock(
            status_code=HTTPStatus.OK,
            json=lambda: {
                "success": True,
                "processors": [
                    {"id": "proc-1", "name": "Classifier"},
                    {"id": "proc-2", "name": "Extractor"},
                ],
                "nextPageToken": None,
            },
        )

        result = client.list_processors()

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["id"] == "proc-1"

    @patch("requests.get")
    def test_list_processors_pagination(
        self, mock_get: MagicMock, client: ExtendClient
    ) -> None:
        """Test listing processors with pagination."""
        mock_get.side_effect = [
            MagicMock(
                status_code=HTTPStatus.OK,
                json=lambda: {
                    "success": True,
                    "processors": [{"id": "proc-1"}],
                    "nextPageToken": "token123",
                },
            ),
            MagicMock(
                status_code=HTTPStatus.OK,
                json=lambda: {
                    "success": True,
                    "processors": [{"id": "proc-2"}],
                    "nextPageToken": None,
                },
            ),
        ]

        result = client.list_processors()

        assert isinstance(result, list)
        assert len(result) == 2
        assert mock_get.call_count == 2

    @patch("requests.get")
    def test_list_processors_failure(
        self, mock_get: MagicMock, client: ExtendClient
    ) -> None:
        """Test list processors failure."""
        mock_get.return_value = MagicMock(
            status_code=HTTPStatus.UNAUTHORIZED,
            content=b"Unauthorized",
        )

        result = client.list_processors()

        assert isinstance(result, ExtendError)
        assert result.status_code == HTTPStatus.UNAUTHORIZED

    @patch("requests.get")
    def test_list_processors_success_false(
        self, mock_get: MagicMock, client: ExtendClient
    ) -> None:
        """Test list processors when success=false."""
        mock_get.return_value = MagicMock(
            status_code=HTTPStatus.OK,
            json=lambda: {"success": False},
        )

        result = client.list_processors()

        assert isinstance(result, ExtendError)

    @patch("requests.delete")
    def test_delete_file_success(
        self, mock_delete: MagicMock, client: ExtendClient
    ) -> None:
        """Test deleting a file."""
        mock_delete.return_value = MagicMock(
            status_code=HTTPStatus.OK,
            json=lambda: {"success": True},
        )

        result = client.delete_file("file-123")

        assert result is True

    @patch("requests.delete")
    def test_delete_file_failure(
        self, mock_delete: MagicMock, client: ExtendClient
    ) -> None:
        """Test delete file failure."""
        mock_delete.return_value = MagicMock(
            status_code=HTTPStatus.NOT_FOUND,
            content=b"File not found",
        )

        result = client.delete_file("invalid-file")

        assert isinstance(result, ExtendError)

    @patch("requests.delete")
    def test_delete_file_success_false(
        self, mock_delete: MagicMock, client: ExtendClient
    ) -> None:
        """Test delete file when success=false."""
        mock_delete.return_value = MagicMock(
            status_code=HTTPStatus.OK,
            json=lambda: {"success": False},
            content=b"Delete failed",
        )

        result = client.delete_file("file-123")

        assert isinstance(result, ExtendError)


class TestProcessorNode:
    """Tests for ProcessorNode."""

    def test_from_dict_classifier(self) -> None:
        """Test creating a classifier ProcessorNode."""
        data = {
            "name": "Lab Classifier",
            "type": "CLASSIFY",
            "extractors": {
                "lipid_panel": {
                    "processor_id": "ext-123",
                    "name": "Lipid Extractor",
                    "type": "EXTRACT",
                },
            },
        }

        node = ProcessorNode.from_dict("class-123", data)

        assert node.processor_id == "class-123"
        assert node.name == "Lab Classifier"
        assert node.processor_type == ProcessorType.CLASSIFY
        assert "lipid_panel" in node.extractors
        assert node.extractors["lipid_panel"].processor_id == "ext-123"

    def test_from_dict_extractor(self) -> None:
        """Test creating an extractor ProcessorNode."""
        data = {
            "name": "Lab Extractor",
            "type": "EXTRACT",
        }

        node = ProcessorNode.from_dict("ext-123", data)

        assert node.processor_id == "ext-123"
        assert node.processor_type == ProcessorType.EXTRACT
        assert node.extractors == {}


class TestProcessorTree:
    """Tests for ProcessorTree."""

    @pytest.fixture
    def processor_tree_json(self) -> str:
        """Create processor tree JSON."""
        import json

        return json.dumps(
            {
                "class-123": {
                    "name": "Lab Classifier",
                    "type": "CLASSIFY",
                    "extractors": {
                        "lipid_panel": {
                            "processor_id": "ext-123",
                            "name": "Lipid Extractor",
                            "type": "EXTRACT",
                        },
                        "cbc": {
                            "processor_id": "ext-456",
                            "name": "CBC Extractor",
                            "type": "EXTRACT",
                        },
                    },
                }
            }
        )

    def test_from_json(self, processor_tree_json: str) -> None:
        """Test parsing processor tree from JSON."""
        tree = ProcessorTree.from_json(processor_tree_json)

        assert "class-123" in tree.classifiers
        assert tree.classifiers["class-123"].name == "Lab Classifier"

    def test_get_first_classifier(self, processor_tree_json: str) -> None:
        """Test getting the first classifier."""
        tree = ProcessorTree.from_json(processor_tree_json)

        classifier = tree.get_first_classifier()

        assert classifier is not None
        assert classifier.processor_id == "class-123"

    def test_get_first_classifier_empty(self) -> None:
        """Test getting classifier when none exist."""
        tree = ProcessorTree(classifiers={})

        classifier = tree.get_first_classifier()

        assert classifier is None

    def test_get_extractor_for_classification(
        self, processor_tree_json: str
    ) -> None:
        """Test getting extractor for a classification result."""
        tree = ProcessorTree.from_json(processor_tree_json)

        extractor = tree.get_extractor_for_classification("class-123", "lipid_panel")

        assert extractor is not None
        assert extractor.processor_id == "ext-123"

    def test_get_extractor_unknown_classifier(
        self, processor_tree_json: str
    ) -> None:
        """Test getting extractor with unknown classifier."""
        tree = ProcessorTree.from_json(processor_tree_json)

        extractor = tree.get_extractor_for_classification("unknown", "lipid_panel")

        assert extractor is None

    def test_get_extractor_unknown_classification(
        self, processor_tree_json: str
    ) -> None:
        """Test getting extractor with unknown classification."""
        tree = ProcessorTree.from_json(processor_tree_json)

        extractor = tree.get_extractor_for_classification("class-123", "unknown")

        assert extractor is None


class TestClassificationResult:
    """Tests for ClassificationResult."""

    def test_creation(self) -> None:
        """Test creating a ClassificationResult."""
        result = ClassificationResult(
            classification_id="lipid_panel",
            classification_type="Lipid Panel",
            confidence=0.95,
        )

        assert result.classification_id == "lipid_panel"
        assert result.classification_type == "Lipid Panel"
        assert result.confidence == 0.95


class TestDocumentProcessor:
    """Tests for DocumentProcessor."""

    @pytest.fixture
    def mock_client(self) -> MagicMock:
        """Create a mock ExtendClient."""
        return MagicMock(spec=ExtendClient)

    @pytest.fixture
    def processor_tree(self) -> ProcessorTree:
        """Create a processor tree."""
        import json

        tree_json = json.dumps(
            {
                "class-123": {
                    "name": "Lab Classifier",
                    "type": "CLASSIFY",
                    "extractors": {
                        "lipid_panel": {
                            "processor_id": "ext-123",
                            "name": "Lipid Extractor",
                            "type": "EXTRACT",
                        },
                    },
                }
            }
        )
        return ProcessorTree.from_json(tree_json)

    def test_process_document_no_classifier(
        self, mock_client: MagicMock
    ) -> None:
        """Test processing with no classifier configured."""
        empty_tree = ProcessorTree(classifiers={})
        processor = DocumentProcessor(mock_client, empty_tree)

        classification, result = processor.process_document("test.pdf", "http://example.com/test.pdf")

        assert classification is None
        assert isinstance(result, ExtendError)
        assert "No classifier configured" in result.message

    def test_process_document_classification_error(
        self, mock_client: MagicMock, processor_tree: ProcessorTree
    ) -> None:
        """Test processing when classification fails."""
        mock_client.run_processor.return_value = ExtendError(
            status_code=500, message="API error"
        )
        processor = DocumentProcessor(mock_client, processor_tree)

        classification, result = processor.process_document("test.pdf", "http://example.com/test.pdf")

        assert classification is None
        assert isinstance(result, ExtendError)

    def test_process_document_wait_error(
        self, mock_client: MagicMock, processor_tree: ProcessorTree
    ) -> None:
        """Test processing when wait_for_completion fails."""
        mock_client.run_processor.return_value = ExtendRunResult(
            run_id="run-123", status=ExtendRunStatus.PENDING
        )
        mock_client.wait_for_completion.return_value = ExtendError(
            status_code=500, message="Timeout"
        )
        processor = DocumentProcessor(mock_client, processor_tree)

        classification, result = processor.process_document("test.pdf", "http://example.com/test.pdf")

        assert classification is None
        assert isinstance(result, ExtendError)

    def test_process_document_classification_failed(
        self, mock_client: MagicMock, processor_tree: ProcessorTree
    ) -> None:
        """Test processing when classification status is FAILED."""
        mock_client.run_processor.return_value = ExtendRunResult(
            run_id="run-123", status=ExtendRunStatus.PENDING
        )
        mock_client.wait_for_completion.return_value = ExtendRunResult(
            run_id="run-123", status=ExtendRunStatus.FAILED, error="Processing failed"
        )
        processor = DocumentProcessor(mock_client, processor_tree)

        classification, result = processor.process_document("test.pdf", "http://example.com/test.pdf")

        assert classification is None
        assert isinstance(result, ExtendError)

    def test_process_document_no_classification_output(
        self, mock_client: MagicMock, processor_tree: ProcessorTree
    ) -> None:
        """Test processing when classification has no output."""
        mock_client.run_processor.return_value = ExtendRunResult(
            run_id="run-123", status=ExtendRunStatus.PENDING
        )
        mock_client.wait_for_completion.return_value = ExtendRunResult(
            run_id="run-123", status=ExtendRunStatus.COMPLETED, output=None
        )
        processor = DocumentProcessor(mock_client, processor_tree)

        classification, result = processor.process_document("test.pdf", "http://example.com/test.pdf")

        assert classification is None
        assert isinstance(result, ExtendError)
        assert "Could not parse classification" in result.message

    def test_process_document_no_extractor_for_classification(
        self, mock_client: MagicMock, processor_tree: ProcessorTree
    ) -> None:
        """Test processing when no extractor matches classification."""
        mock_client.run_processor.return_value = ExtendRunResult(
            run_id="run-123", status=ExtendRunStatus.PENDING
        )
        mock_client.wait_for_completion.return_value = ExtendRunResult(
            run_id="run-123",
            status=ExtendRunStatus.COMPLETED,
            output={"id": "unknown_type", "type": "Unknown"},
        )
        processor = DocumentProcessor(mock_client, processor_tree)

        classification, result = processor.process_document("test.pdf", "http://example.com/test.pdf")

        assert classification is not None
        assert classification.classification_id == "unknown_type"
        assert isinstance(result, ExtendRunResult)
        assert result.output.get("skipped") is True

    def test_process_document_full_success(
        self, mock_client: MagicMock, processor_tree: ProcessorTree
    ) -> None:
        """Test successful document processing."""
        # Classification
        mock_client.run_processor.side_effect = [
            ExtendRunResult(run_id="classify-run", status=ExtendRunStatus.PENDING),
            ExtendRunResult(run_id="extract-run", status=ExtendRunStatus.PENDING),
        ]
        mock_client.wait_for_completion.side_effect = [
            ExtendRunResult(
                run_id="classify-run",
                status=ExtendRunStatus.COMPLETED,
                output={"id": "lipid_panel", "type": "Lipid Panel", "confidence": 0.95},
            ),
            ExtendRunResult(
                run_id="extract-run",
                status=ExtendRunStatus.COMPLETED,
                output={"patient_name": "John Doe", "tests": []},
            ),
        ]
        processor = DocumentProcessor(mock_client, processor_tree)

        classification, result = processor.process_document("test.pdf", "http://example.com/test.pdf")

        assert classification is not None
        assert classification.classification_id == "lipid_panel"
        assert classification.confidence == 0.95
        assert isinstance(result, ExtendRunResult)
        assert result.status == ExtendRunStatus.COMPLETED

    def test_process_document_extraction_error(
        self, mock_client: MagicMock, processor_tree: ProcessorTree
    ) -> None:
        """Test processing when extraction fails."""
        mock_client.run_processor.side_effect = [
            ExtendRunResult(run_id="classify-run", status=ExtendRunStatus.PENDING),
            ExtendError(status_code=500, message="Extraction failed"),
        ]
        mock_client.wait_for_completion.return_value = ExtendRunResult(
            run_id="classify-run",
            status=ExtendRunStatus.COMPLETED,
            output={"id": "lipid_panel", "type": "Lipid Panel"},
        )
        processor = DocumentProcessor(mock_client, processor_tree)

        classification, result = processor.process_document("test.pdf", "http://example.com/test.pdf")

        assert classification is not None
        assert isinstance(result, ExtendError)
