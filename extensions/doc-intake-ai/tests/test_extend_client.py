"""Tests for Extend AI client functions."""

import pytest
from typing import Any
from unittest.mock import MagicMock, patch

from doc_intake_ai.extend_client import (
    _slugify,
    _build_slug_map,
    _parse_min_confidence,
    _parse_extraction,
    _build_extraction_schema,
    _format_error,
    start_extraction,
    start_categorization,
    start_template_extraction,
    parse_categorization_result,
    parse_template_result,
)
from doc_intake_ai.models import DocumentExtraction


class TestSlugify:
    """Test name slugification."""

    @pytest.mark.parametrize("value,expected", [
        ("Lab Report", "lab_report"),
        ("Imaging Report", "imaging_report"),
        ("CT Scan - Head", "ct_scan_head"),
        ("  spaced  ", "spaced"),
        ("MRI/CT", "mri_ct"),
        ("Test (with parens)", "test_with_parens"),
        ("UPPERCASE", "uppercase"),
        ("a--b", "a_b"),
        ("  ", ""),
        ("123", "123"),
        ("Test & Report", "test_report"),
    ])
    def test_slugification(self, value: str, expected: str) -> None:
        assert _slugify(value) == expected


class TestBuildSlugMap:
    """Test document type to slug mapping."""

    def test_builds_mapping(self) -> None:
        types = [
            {"name": "Lab Report", "key": "lab"},
            {"name": "Imaging Report", "key": "imaging"},
        ]
        result = _build_slug_map(types)

        assert "lab_report" in result
        assert "imaging_report" in result
        assert result["lab_report"]["key"] == "lab"

    def test_skips_duplicates(self) -> None:
        types = [
            {"name": "Lab Report", "key": "lab1"},
            {"name": "Lab Report", "key": "lab2"},
        ]
        result = _build_slug_map(types)

        assert len(result) == 1
        assert result["lab_report"]["key"] == "lab1"

    def test_skips_missing_names(self) -> None:
        types: list[dict[str, Any]] = [
            {"name": "Lab Report", "key": "lab"},
            {"key": "no_name"},
            {"name": None, "key": "null_name"},
        ]
        result = _build_slug_map(types)

        assert len(result) == 1
        assert "lab_report" in result

    def test_empty_list(self) -> None:
        assert _build_slug_map([]) == {}


class TestParseMinConfidence:
    """Test OCR confidence extraction."""

    def test_returns_minimum(self) -> None:
        metadata = {
            "field1": {"ocrConfidence": 0.95},
            "field2": {"ocrConfidence": 0.85},
            "field3": {"ocrConfidence": 0.90},
        }
        assert _parse_min_confidence(metadata) == 0.85

    def test_single_field(self) -> None:
        metadata = {"field1": {"ocrConfidence": 0.95}}
        assert _parse_min_confidence(metadata) == 0.95

    def test_none_when_empty(self) -> None:
        assert _parse_min_confidence({}) is None

    def test_none_when_none(self) -> None:
        assert _parse_min_confidence(None) is None

    def test_skips_non_dict_values(self) -> None:
        metadata = {
            "field1": {"ocrConfidence": 0.95},
            "field2": "not a dict",
            "field3": None,
        }
        assert _parse_min_confidence(metadata) == 0.95

    def test_skips_missing_confidence(self) -> None:
        metadata = {
            "field1": {"ocrConfidence": 0.95},
            "field2": {"other": "data"},
        }
        assert _parse_min_confidence(metadata) == 0.95

    def test_handles_int_confidence(self) -> None:
        metadata = {"field1": {"ocrConfidence": 1}}
        assert _parse_min_confidence(metadata) == 1.0

    def test_none_when_no_valid_scores(self) -> None:
        metadata = {
            "field1": {"other": "data"},
            "field2": "string",
        }
        assert _parse_min_confidence(metadata) is None


class TestParseExtraction:
    """Test extraction data parsing."""

    def test_valid_data(self) -> None:
        raw = {
            "document_type": "lab_report",
            "loinc_codes": "11580-8",
            "patient_id": "MRN123",
        }
        result = _parse_extraction(raw)

        assert isinstance(result, DocumentExtraction)
        assert result.document_type == "lab_report"
        assert result.loinc_codes == "11580-8"
        assert result.patient_id == "MRN123"

    def test_extra_fields_preserved(self) -> None:
        raw = {
            "document_type": "lab_report",
            "custom_field": "custom_value",
        }
        result = _parse_extraction(raw)

        assert result.document_type == "lab_report"
        assert result.model_extra is not None
        assert result.model_extra.get("custom_field") == "custom_value"

    def test_empty_data(self) -> None:
        result = _parse_extraction({})
        assert isinstance(result, DocumentExtraction)
        assert result.document_type is None

    def test_handles_invalid_types_gracefully(self) -> None:
        raw = {
            "document_type": 123,
            "loinc_codes": {"nested": "object"},
        }
        result = _parse_extraction(raw)
        assert isinstance(result, DocumentExtraction)


class TestBuildExtractionSchema:
    """Test extraction schema building."""

    def test_includes_enum_for_type_slugs(self) -> None:
        schema = _build_extraction_schema(["lab_report", "imaging_report"])
        props = schema["schema"]["properties"]
        assert "document_type" in props
        assert props["document_type"]["enum"] == ["lab_report", "imaging_report"]

    def test_empty_slugs_no_enum(self) -> None:
        schema = _build_extraction_schema([])
        props = schema["schema"]["properties"]
        assert "enum" not in props["document_type"]

    def test_includes_patient_fields(self) -> None:
        schema = _build_extraction_schema(["lab"])
        props = schema["schema"]["properties"]
        assert "patient_first_name" in props
        assert "patient_last_name" in props
        assert "date_of_birth" in props

    def test_includes_practitioner_fields(self) -> None:
        schema = _build_extraction_schema(["lab"])
        props = schema["schema"]["properties"]
        assert "practitioner_npi" in props
        assert "practitioner_name" in props


class TestStartExtraction:
    """Test async extraction start."""

    @patch("doc_intake_ai.extend_client.requests.post")
    def test_returns_run_id_on_success(self, mock_post: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"processorRun": {"id": "dpr_run123"}}
        mock_post.return_value = mock_response

        result = start_extraction("key", "proc", "https://s3/doc.pdf", {})
        assert result == "dpr_run123"
        assert mock_post.call_count == 1

    @patch("doc_intake_ai.extend_client.requests.post")
    def test_no_sync_in_payload(self, mock_post: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"processorRun": {"id": "dpr_run123"}}
        mock_post.return_value = mock_response

        start_extraction("key", "proc", "https://s3/doc.pdf", {})

        call_kwargs = mock_post.call_args
        payload = call_kwargs[1]["json"]
        assert "sync" not in payload

    @patch("doc_intake_ai.extend_client.requests.post")
    def test_returns_none_on_missing_run_id(self, mock_post: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"processorRun": {}}
        mock_post.return_value = mock_response

        result = start_extraction("key", "proc", "https://s3/doc.pdf", {})
        assert result is None

    @patch("doc_intake_ai.extend_client.requests.post")
    def test_returns_none_on_client_error(self, mock_post: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 422
        mock_response.json.return_value = {"error": {"message": "Invalid schema"}}
        mock_post.return_value = mock_response

        result = start_extraction("key", "proc", "https://s3/doc.pdf", {})
        assert result is None
        assert mock_post.call_count == 1

    @patch("doc_intake_ai.extend_client.time.sleep")
    @patch("doc_intake_ai.extend_client.requests.post")
    def test_retries_on_500(self, mock_post: MagicMock, mock_sleep: MagicMock) -> None:
        error_response = MagicMock(status_code=500)
        success_response = MagicMock(status_code=200)
        success_response.json.return_value = {"processorRun": {"id": "dpr_run123"}}
        mock_post.side_effect = [error_response, success_response]

        result = start_extraction("key", "proc", "https://s3/doc.pdf", {})
        assert result == "dpr_run123"
        assert mock_post.call_count == 2
        mock_sleep.assert_called_once()

    @patch("doc_intake_ai.extend_client.time.sleep")
    @patch("doc_intake_ai.extend_client.requests.post")
    def test_returns_none_after_max_retries(self, mock_post: MagicMock, mock_sleep: MagicMock) -> None:
        error_response = MagicMock(status_code=500)
        mock_post.return_value = error_response

        result = start_extraction("key", "proc", "https://s3/doc.pdf", {})
        assert result is None

    @patch("doc_intake_ai.extend_client.time.sleep")
    @patch("doc_intake_ai.extend_client.requests.post")
    def test_retries_on_request_exception(self, mock_post: MagicMock, mock_sleep: MagicMock) -> None:
        import requests
        success_response = MagicMock(status_code=200)
        success_response.json.return_value = {"processorRun": {"id": "dpr_run123"}}
        mock_post.side_effect = [
            requests.RequestException("Connection error"),
            success_response,
        ]

        result = start_extraction("key", "proc", "https://s3/doc.pdf", {})
        assert result == "dpr_run123"

    @patch("doc_intake_ai.extend_client.time.sleep")
    @patch("doc_intake_ai.extend_client.requests.post")
    def test_returns_none_after_all_exceptions(self, mock_post: MagicMock, mock_sleep: MagicMock) -> None:
        import requests
        mock_post.side_effect = requests.RequestException("Connection error")

        result = start_extraction("key", "proc", "https://s3/doc.pdf", {})
        assert result is None


class TestStartCategorization:
    """Test the start_categorization orchestrator."""

    def test_missing_content_url(self) -> None:
        result = start_categorization("", [], "key", "proc")
        assert result is None

    @patch("doc_intake_ai.extend_client.start_extraction")
    def test_delegates_to_start_extraction(self, mock_start: MagicMock) -> None:
        mock_start.return_value = "dpr_run123"
        result = start_categorization("https://s3/doc.pdf", [], "key", "proc")
        assert result == "dpr_run123"
        mock_start.assert_called_once()


class TestStartTemplateExtraction:
    """Test the start_template_extraction orchestrator."""

    def test_missing_content_url(self) -> None:
        result = start_template_extraction("", {}, "key", "proc")
        assert result is None

    @patch("doc_intake_ai.extend_client.start_extraction")
    def test_delegates_to_start_extraction(self, mock_start: MagicMock) -> None:
        mock_start.return_value = "dpr_run456"
        result = start_template_extraction("https://s3/doc.pdf", {"schema": {}}, "key", "proc")
        assert result == "dpr_run456"
        mock_start.assert_called_once()


class TestParseCategorization:
    """Test parse_categorization_result."""

    def test_successful_parse(self, sample_available_types: list) -> None:
        processor_run = {
            "output": {
                "value": {
                    "document_type": "lab_report",
                    "patient_first_name": "John",
                    "patient_last_name": "Doe",
                },
                "metadata": {"document_type": {"ocrConfidence": 0.95}},
            },
        }
        result = parse_categorization_result(processor_run, sample_available_types)

        assert result.ok
        assert result.document_type is not None
        assert result.document_type["key"] == "lab_report"
        assert result.extraction.patient_first_name == "John"
        assert result.confidence == 0.95

    def test_no_matching_type(self) -> None:
        processor_run = {
            "output": {
                "value": {"document_type": "unknown_type"},
                "metadata": {},
            },
        }
        result = parse_categorization_result(processor_run, [])

        assert result.ok
        assert result.document_type is None

    def test_empty_output(self) -> None:
        result = parse_categorization_result({}, [])
        assert result.ok
        assert result.document_type is None


class TestParseTemplateResult:
    """Test parse_template_result."""

    def test_extracts_value_and_metadata(self) -> None:
        processor_run = {
            "output": {
                "value": {"11580-8": "4.5", "3016-3": "1.2"},
                "metadata": {"11580-8": {"ocrConfidence": 0.92}},
            },
        }
        value, metadata = parse_template_result(processor_run)

        assert value == {"11580-8": "4.5", "3016-3": "1.2"}
        assert metadata == {"11580-8": {"ocrConfidence": 0.92}}

    def test_empty_output(self) -> None:
        value, metadata = parse_template_result({})
        assert value == {}
        assert metadata is None


class TestFormatError:
    """Test API error response formatting."""

    def test_error_message_from_nested_error(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 422
        mock_response.json.return_value = {"error": {"message": "Invalid schema"}}

        result = _format_error(mock_response)
        assert result == "Extend AI error: Invalid schema"

    def test_error_message_from_top_level(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {"message": "Bad request"}

        result = _format_error(mock_response)
        assert result == "Extend AI error: Bad request"

    def test_fallback_to_status_code(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.json.return_value = {}

        result = _format_error(mock_response)
        assert result == "Extend AI error: HTTP 500"

    def test_json_parse_failure(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 502
        mock_response.json.side_effect = ValueError("Not JSON")

        result = _format_error(mock_response)
        assert result == "Extend AI error: HTTP 502"
