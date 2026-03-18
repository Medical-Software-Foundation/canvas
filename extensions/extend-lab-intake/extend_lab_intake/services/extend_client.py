"""Extend AI client for lab report extraction."""

import json
from enum import Enum
from http import HTTPStatus
from typing import Any
from urllib.parse import urlencode

import requests


class ProcessorType(Enum):
    """Types of Extend AI processors."""

    CLASSIFY = "CLASSIFY"
    EXTRACT = "EXTRACT"


class ExtendRunStatus(Enum):
    """Possible statuses for an Extend AI processor run."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ExtendRunResult:
    """Result from an Extend AI processor run."""

    def __init__(
        self,
        run_id: str,
        status: ExtendRunStatus,
        output: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        self.run_id = run_id
        self.status = status
        self.output = output
        self.error = error

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExtendRunResult":
        """Create from API response dict."""
        return cls(
            run_id=data.get("id", ""),
            status=ExtendRunStatus(data.get("status", "PENDING")),
            output=data.get("output"),
            error=data.get("error"),
        )


class ExtendError:
    """Error response from Extend AI."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message


class ExtendClient:
    """Client for Extend AI document extraction API.

    This client handles running processors on lab report PDFs and retrieving
    extraction results.
    """

    BASE_URL = "https://api.extend.ai"
    API_VERSION = "2025-04-21"

    def __init__(self, api_key: str) -> None:
        """Initialize the Extend AI client.

        Args:
            api_key: The Extend AI API key
        """
        self.api_key = api_key
        self.headers = {
            "x-extend-api-version": self.API_VERSION,
            "Authorization": f"Bearer {api_key}",
        }

    def run_processor(
        self,
        processor_id: str,
        file_name: str,
        file_url: str,
        config: dict[str, Any] | None = None,
    ) -> ExtendRunResult | ExtendError:
        """Run a processor on a document.

        Args:
            processor_id: The ID of the Extend processor to run
            file_name: Name of the file being processed
            file_url: URL where the file can be accessed (e.g., presigned S3 URL)
            config: Optional processor configuration override

        Returns:
            ExtendRunResult on success, ExtendError on failure
        """
        headers = {**self.headers, "Content-Type": "application/json"}
        payload: dict[str, Any] = {
            "processorId": processor_id,
            "file": {
                "fileName": file_name,
                "fileUrl": file_url,
            },
        }

        if config is not None:
            payload["config"] = config

        response = requests.post(
            f"{self.BASE_URL}/processor_runs",
            headers=headers,
            json=payload,
            timeout=60.0,
        )

        if response.status_code == HTTPStatus.OK:
            data = response.json()
            if data.get("success"):
                return ExtendRunResult.from_dict(data.get("processorRun", {}))

        return ExtendError(
            status_code=response.status_code,
            message=response.content.decode() if response.content else "Unknown error",
        )

    def get_run_status(self, run_id: str) -> ExtendRunResult | ExtendError:
        """Get the status of a processor run.

        Args:
            run_id: The ID of the processor run

        Returns:
            ExtendRunResult with current status, or ExtendError on failure
        """
        response = requests.get(
            f"{self.BASE_URL}/processor_runs/{run_id}",
            headers=self.headers,
            timeout=30.0,
        )

        if response.status_code == HTTPStatus.OK:
            data = response.json()
            if data.get("success"):
                return ExtendRunResult.from_dict(data.get("processorRun", {}))

        return ExtendError(
            status_code=response.status_code,
            message=response.content.decode() if response.content else "Unknown error",
        )

    def wait_for_completion(
        self,
        run_id: str,
        max_attempts: int = 60,
        poll_interval_seconds: float = 2.0,
    ) -> ExtendRunResult | ExtendError:
        """Poll for processor run completion.

        Args:
            run_id: The ID of the processor run
            max_attempts: Maximum number of polling attempts
            poll_interval_seconds: Seconds between poll attempts

        Returns:
            Final ExtendRunResult or ExtendError
        """
        import time

        for _ in range(max_attempts):
            result = self.get_run_status(run_id)

            if isinstance(result, ExtendError):
                return result

            if result.status in (ExtendRunStatus.COMPLETED, ExtendRunStatus.PROCESSED, ExtendRunStatus.FAILED):
                return result

            time.sleep(poll_interval_seconds)

        return ExtendError(
            status_code=HTTPStatus.REQUEST_TIMEOUT,
            message=f"Processor run {run_id} did not complete within timeout",
        )

    def list_processors(self) -> list[dict[str, Any]] | ExtendError:
        """List available processors.

        Returns:
            List of processor metadata dicts, or ExtendError on failure
        """
        result: list[dict[str, Any]] = []
        path = "/processors"

        while True:
            response = requests.get(
                f"{self.BASE_URL}{path}",
                headers=self.headers,
                timeout=30.0,
            )

            if response.status_code != HTTPStatus.OK:
                return ExtendError(
                    status_code=response.status_code,
                    message=response.content.decode() if response.content else "Unknown error",
                )

            data = response.json()
            if not data.get("success"):
                return ExtendError(
                    status_code=response.status_code,
                    message="API returned success=false",
                )

            result.extend(data.get("processors", []))

            next_page_token = data.get("nextPageToken")
            if not next_page_token:
                break

            path = f"/processors?{urlencode({'nextPageToken': next_page_token})}"

        return result

    def delete_file(self, file_id: str) -> bool | ExtendError:
        """Delete a file from Extend AI.

        Args:
            file_id: The ID of the file to delete

        Returns:
            True on success, ExtendError on failure
        """
        response = requests.delete(
            f"{self.BASE_URL}/files/{file_id}",
            headers=self.headers,
            timeout=30.0,
        )

        if response.status_code == HTTPStatus.OK:
            data = response.json()
            if data.get("success"):
                return True

        return ExtendError(
            status_code=response.status_code,
            message=response.content.decode() if response.content else "Unknown error",
        )


class ClassificationResult:
    """Result from a classification processor run."""

    def __init__(
        self,
        classification_id: str,
        classification_type: str,
        confidence: float | None = None,
    ) -> None:
        self.classification_id = classification_id
        self.classification_type = classification_type
        self.confidence = confidence


class ProcessorNode:
    """A node in the processor tree representing a single processor."""

    def __init__(
        self,
        processor_id: str,
        name: str,
        processor_type: ProcessorType,
        extractors: dict[str, "ProcessorNode"] | None = None,
    ) -> None:
        self.processor_id = processor_id
        self.name = name
        self.processor_type = processor_type
        # For classifiers, maps classification_id -> extractor ProcessorNode
        self.extractors = extractors or {}

    @classmethod
    def from_dict(cls, processor_id: str, data: dict[str, Any]) -> "ProcessorNode":
        """Create a ProcessorNode from a dict representation."""
        processor_type = ProcessorType(data.get("type", "EXTRACT"))
        extractors: dict[str, ProcessorNode] = {}

        if processor_type == ProcessorType.CLASSIFY:
            extractors_data = data.get("extractors", {})
            for ext_id, ext_data in extractors_data.items():
                # For extractors, the actual processor_id is in the data, not the key
                actual_processor_id = ext_data.get("processor_id", ext_id)
                extractors[ext_id] = cls.from_dict(actual_processor_id, ext_data)

        return cls(
            processor_id=processor_id,
            name=data.get("name", ""),
            processor_type=processor_type,
            extractors=extractors,
        )


class ProcessorTree:
    """Tree structure mapping classifiers to extractors.

    Expected JSON structure:
    {
        "dp_classifier_id": {
            "name": "Lipid Panel Classifier",
            "type": "CLASSIFY",
            "extractors": {
                "lipid_panel": {
                    "processor_id": "dp_extractor_id",
                    "name": "Lab Report Extractor",
                    "type": "EXTRACT"
                }
            }
        }
    }

    The extractors dict is keyed by classification_id (the result from the classifier),
    which maps to the extractor processor to use for that classification.
    """

    def __init__(self, classifiers: dict[str, ProcessorNode]) -> None:
        self.classifiers = classifiers

    @classmethod
    def from_json(cls, json_str: str) -> "ProcessorTree":
        """Parse processor tree from JSON string (secret value)."""
        data = json.loads(json_str)
        classifiers: dict[str, ProcessorNode] = {}

        for processor_id, processor_data in data.items():
            classifiers[processor_id] = ProcessorNode.from_dict(
                processor_id, processor_data
            )

        return cls(classifiers=classifiers)

    def get_first_classifier(self) -> ProcessorNode | None:
        """Get the first classifier in the tree."""
        if self.classifiers:
            return next(iter(self.classifiers.values()))
        return None

    def get_extractor_for_classification(
        self,
        classifier_id: str,
        classification_id: str,
    ) -> ProcessorNode | None:
        """Get the extractor processor for a given classification result.

        Args:
            classifier_id: The ID of the classifier that produced the result
            classification_id: The classification ID from the classifier output

        Returns:
            The ProcessorNode for the extractor, or None if not found
        """
        classifier = self.classifiers.get(classifier_id)
        if not classifier:
            return None

        return classifier.extractors.get(classification_id)


class DocumentProcessor:
    """High-level processor that handles the classify -> extract flow."""

    def __init__(self, client: ExtendClient, processor_tree: ProcessorTree) -> None:
        self.client = client
        self.processor_tree = processor_tree

    def process_document(
        self,
        file_name: str,
        file_url: str,
    ) -> tuple[ClassificationResult | None, ExtendRunResult | ExtendError]:
        """Process a document through classification and extraction.

        1. Run the classifier to determine document type
        2. Based on classification, run the appropriate extractor
        3. Return both classification and extraction results

        Args:
            file_name: Name of the file
            file_url: URL where the file can be accessed

        Returns:
            Tuple of (ClassificationResult, ExtendRunResult/ExtendError)
            ClassificationResult may be None if no classifier configured
        """
        classifier = self.processor_tree.get_first_classifier()

        if not classifier:
            return None, ExtendError(
                status_code=HTTPStatus.BAD_REQUEST,
                message="No classifier configured in processor tree",
            )

        # Step 1: Run classification
        classify_result = self.client.run_processor(
            processor_id=classifier.processor_id,
            file_name=file_name,
            file_url=file_url,
        )

        if isinstance(classify_result, ExtendError):
            return None, classify_result

        # Wait for classification to complete
        classify_result = self.client.wait_for_completion(classify_result.run_id)

        if isinstance(classify_result, ExtendError):
            return None, classify_result

        if classify_result.status == ExtendRunStatus.FAILED:
            return None, ExtendError(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                message=classify_result.error or "Classification failed",
            )

        # Parse classification result
        classification = self._parse_classification(classify_result)
        if not classification:
            return None, ExtendError(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                message="Could not parse classification result",
            )

        # Step 2: Find the appropriate extractor
        extractor = self.processor_tree.get_extractor_for_classification(
            classifier.processor_id,
            classification.classification_id,
        )

        if not extractor:
            # No extractor for this classification - return classification only
            return classification, ExtendRunResult(
                run_id="",
                status=ExtendRunStatus.COMPLETED,
                output={"skipped": True, "reason": f"No extractor for classification: {classification.classification_id}"},
            )

        # Step 3: Run extraction
        extract_result = self.client.run_processor(
            processor_id=extractor.processor_id,
            file_name=file_name,
            file_url=file_url,
        )

        if isinstance(extract_result, ExtendError):
            return classification, extract_result

        # Wait for extraction to complete
        extract_result = self.client.wait_for_completion(extract_result.run_id)

        return classification, extract_result

    def _parse_classification(
        self, result: ExtendRunResult
    ) -> ClassificationResult | None:
        """Parse classification from processor run output."""
        if not result.output:
            return None

        # Extend AI returns classification directly in output (id, type, confidence)
        classification_id = result.output.get("id", "")
        classification_type = result.output.get("type", "")

        if not classification_id and not classification_type:
            return None

        return ClassificationResult(
            classification_id=classification_id,
            classification_type=classification_type,
            confidence=result.output.get("confidence"),
        )
