"""Tests for lab result summarizer."""

from unittest.mock import MagicMock

import pytest

from extend_lab_intake.services.fhir_client import LabReport, LabTest, LabValue
from extend_lab_intake.services.llm_client import LLMClient
from extend_lab_intake.services.summarizer import LabResultSummarizer


class TestLabResultSummarizer:
    """Tests for LabResultSummarizer."""

    @pytest.fixture
    def mock_llm_client(self) -> MagicMock:
        """Create a mock LLM client."""
        client = MagicMock(spec=LLMClient)
        client.reset_messages = MagicMock()
        client.chat = MagicMock(
            return_value={
                "success": True,
                "content": "Summary: All values within normal limits.",
            }
        )
        return client

    @pytest.fixture
    def summarizer(self, mock_llm_client: MagicMock) -> LabResultSummarizer:
        """Create a LabResultSummarizer instance."""
        return LabResultSummarizer(mock_llm_client)

    @pytest.fixture
    def sample_lab_report(self) -> LabReport:
        """Create a sample lab report."""
        test = LabTest(
            code="lipid-panel",
            display="Lipid Panel",
            effective_date="2024-01-15",
        )
        test.values = [
            LabValue(
                code="cholesterol",
                display="Total Cholesterol",
                value="200",
                unit="mg/dL",
                reference_range_text="<200",
                is_abnormal=False,
            ),
            LabValue(
                code="ldl",
                display="LDL Cholesterol",
                value="150",
                unit="mg/dL",
                reference_range_text="<100",
                is_abnormal=True,
            ),
        ]

        return LabReport(
            patient_id="patient-123",
            effective_date="2024-01-15",
            tests=[test],
            pdf_data=b"pdf-content",
        )

    def test_summarize_no_tests(
        self, summarizer: LabResultSummarizer, mock_llm_client: MagicMock
    ) -> None:
        """Test summarization with no tests."""
        report = LabReport(
            patient_id="patient-123",
            effective_date="2024-01-15",
            tests=[],
            pdf_data=b"pdf",
        )

        result = summarizer.summarize(report)

        assert result == "No lab test results to summarize."
        mock_llm_client.chat.assert_not_called()

    def test_summarize_success(
        self,
        summarizer: LabResultSummarizer,
        mock_llm_client: MagicMock,
        sample_lab_report: LabReport,
    ) -> None:
        """Test successful summarization."""
        result = summarizer.summarize(sample_lab_report)

        assert result == "Summary: All values within normal limits."
        mock_llm_client.reset_messages.assert_called_once()
        mock_llm_client.chat.assert_called_once()

    def test_summarize_llm_failure_fallback(
        self,
        summarizer: LabResultSummarizer,
        mock_llm_client: MagicMock,
        sample_lab_report: LabReport,
    ) -> None:
        """Test fallback when LLM fails."""
        mock_llm_client.chat.return_value = {
            "success": False,
            "error": "API error",
        }

        result = summarizer.summarize(sample_lab_report)

        # Should use fallback summary
        assert "ABNORMAL" in result or "Normal" in result

    def test_format_results_for_llm(
        self, summarizer: LabResultSummarizer, sample_lab_report: LabReport
    ) -> None:
        """Test formatting results for LLM input."""
        result = summarizer._format_results_for_llm(sample_lab_report)

        assert "2024-01-15" in result
        assert "Lipid Panel" in result
        assert "Total Cholesterol" in result
        assert "200 mg/dL" in result
        assert "**ABNORMAL**" in result  # For LDL

    def test_format_results_with_numeric_ranges(
        self, summarizer: LabResultSummarizer
    ) -> None:
        """Test formatting with numeric reference ranges."""
        test = LabTest(
            code="glucose",
            display="Glucose",
            effective_date="2024-01-15",
        )
        test.values = [
            LabValue(
                code="glucose",
                display="Fasting Glucose",
                value="100",
                unit="mg/dL",
                reference_range_low=70.0,
                reference_range_high=100.0,
            ),
        ]

        report = LabReport(
            patient_id="patient-123",
            effective_date="2024-01-15",
            tests=[test],
            pdf_data=b"pdf",
        )

        result = summarizer._format_results_for_llm(report)

        assert "(Ref: 70.0-100.0)" in result

    def test_format_results_no_value(
        self, summarizer: LabResultSummarizer
    ) -> None:
        """Test formatting when value is None."""
        test = LabTest(
            code="test",
            display="Test",
            effective_date="2024-01-15",
        )
        test.values = [
            LabValue(
                code="test",
                display="Some Test",
                value=None,
                unit="",
            ),
        ]

        report = LabReport(
            patient_id="patient-123",
            effective_date="2024-01-15",
            tests=[test],
            pdf_data=b"pdf",
        )

        result = summarizer._format_results_for_llm(report)

        assert "No value" in result

    def test_format_results_value_without_unit(
        self, summarizer: LabResultSummarizer
    ) -> None:
        """Test formatting value without unit."""
        test = LabTest(
            code="test",
            display="Test",
            effective_date="2024-01-15",
        )
        test.values = [
            LabValue(
                code="test",
                display="Some Test",
                value="positive",
                unit="",
            ),
        ]

        report = LabReport(
            patient_id="patient-123",
            effective_date="2024-01-15",
            tests=[test],
            pdf_data=b"pdf",
        )

        result = summarizer._format_results_for_llm(report)

        assert "positive" in result

    def test_fallback_summary_with_abnormal(
        self, summarizer: LabResultSummarizer, sample_lab_report: LabReport
    ) -> None:
        """Test fallback summary with abnormal values."""
        result = summarizer._fallback_summary(sample_lab_report)

        assert "ABNORMAL" in result
        assert "LDL" in result

    def test_fallback_summary_all_normal(
        self, summarizer: LabResultSummarizer
    ) -> None:
        """Test fallback summary with all normal values."""
        test = LabTest(
            code="cbc",
            display="Complete Blood Count",
            effective_date="2024-01-15",
        )
        test.values = [
            LabValue(
                code="wbc",
                display="WBC",
                value="7.0",
                unit="K/uL",
                is_abnormal=False,
            ),
        ]

        report = LabReport(
            patient_id="patient-123",
            effective_date="2024-01-15",
            tests=[test],
            pdf_data=b"pdf",
        )

        result = summarizer._fallback_summary(report)

        assert "Normal" in result
        assert "Complete Blood Count" in result

    def test_fallback_summary_empty_tests(
        self, summarizer: LabResultSummarizer
    ) -> None:
        """Test fallback summary with empty tests."""
        report = LabReport(
            patient_id="patient-123",
            effective_date="2024-01-15",
            tests=[],
            pdf_data=b"pdf",
        )

        result = summarizer._fallback_summary(report)

        assert result == "Lab results processed."

    def test_summarize_from_extend_output_success(
        self, summarizer: LabResultSummarizer, mock_llm_client: MagicMock
    ) -> None:
        """Test summarization from Extend AI output."""
        extend_output = {
            "tests": [
                {"name": "Cholesterol", "value": "200", "unit": "mg/dL"},
            ]
        }

        result = summarizer.summarize_from_extend_output(extend_output)

        assert result == "Summary: All values within normal limits."
        mock_llm_client.chat.assert_called_once()

    def test_summarize_from_extend_output_failure(
        self, summarizer: LabResultSummarizer, mock_llm_client: MagicMock
    ) -> None:
        """Test summarization from Extend AI output when LLM fails."""
        mock_llm_client.chat.return_value = {
            "success": False,
            "error": "API error",
        }

        extend_output = {"tests": []}

        result = summarizer.summarize_from_extend_output(extend_output)

        assert "Lab results processed" in result

    def test_format_extend_output_with_tests(
        self, summarizer: LabResultSummarizer
    ) -> None:
        """Test formatting Extend AI output with tests."""
        output = {
            "tests": [
                {
                    "name": "Cholesterol",
                    "value": "200",
                    "unit": "mg/dL",
                    "reference_range": "<200",
                    "abnormal": False,
                },
                {
                    "test_name": "LDL",
                    "result": "150",
                    "units": "mg/dL",
                    "ref_range": "<100",
                    "is_abnormal": True,
                },
            ]
        }

        result = summarizer._format_extend_output(output)

        assert "Cholesterol" in result
        assert "LDL" in result
        assert "**ABNORMAL**" in result

    def test_format_extend_output_with_results_key(
        self, summarizer: LabResultSummarizer
    ) -> None:
        """Test formatting Extend AI output with 'results' key."""
        output = {
            "results": [
                {"name": "Glucose", "value": "100", "unit": "mg/dL"},
            ]
        }

        result = summarizer._format_extend_output(output)

        assert "Glucose" in result

    def test_format_extend_output_fallback_json(
        self, summarizer: LabResultSummarizer
    ) -> None:
        """Test formatting Extend AI output falls back to JSON."""
        output = {"custom_field": "value"}

        result = summarizer._format_extend_output(output)

        assert "custom_field" in result
        assert '"value"' in result
