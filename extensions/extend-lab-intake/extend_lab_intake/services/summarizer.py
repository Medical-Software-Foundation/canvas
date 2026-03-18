"""Lab result summarization service using LLM."""

from __future__ import annotations

from typing import Any

from logger import log

from extend_lab_intake.services.fhir_client import LabReport, LabTest, LabValue
from extend_lab_intake.services.llm_client import LLMClient


class LabResultSummarizer:
    """Service to generate concise clinical summaries of lab results."""

    SYSTEM_PROMPT = """You are a clinical assistant summarizing lab results for healthcare providers.

Your summary should:
1. Highlight any ABNORMAL values first (critical findings)
2. Group related tests together (e.g., all liver function tests)
3. Note any values outside reference ranges
4. Be concise but clinically useful (max 3-4 sentences per test panel)
5. Use standard medical abbreviations where appropriate

Format your summary as plain text, suitable for inclusion in a task comment.
Do NOT include JSON formatting - just provide a readable clinical summary.

If there are no abnormal values, simply state "All values within normal limits" and list the tests performed."""

    def __init__(self, llm_client: LLMClient) -> None:
        """Initialize the summarizer.

        Args:
            llm_client: LLM client for generating summaries
        """
        self.llm_client = llm_client

    def summarize(self, report: LabReport) -> str:
        """Generate a clinical summary of lab results.

        Args:
            report: The lab report to summarize

        Returns:
            A concise clinical summary string
        """
        if not report.tests:
            return "No lab test results to summarize."

        # Build a structured description of the lab results
        results_text = self._format_results_for_llm(report)

        user_prompt = f"""Please summarize the following lab results:

{results_text}

Provide a brief clinical summary highlighting any abnormal findings."""

        self.llm_client.reset_messages()
        result = self.llm_client.chat(
            system_prompt=self.SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )

        if not result["success"]:
            log.warning(f"LLM summarization failed: {result['error']}")
            return self._fallback_summary(report)

        return result["content"].strip()

    def _format_results_for_llm(self, report: LabReport) -> str:
        """Format lab results as text for LLM input."""
        lines = [f"Lab Report Date: {report.effective_date}"]
        lines.append("")

        for test in report.tests:
            lines.append(f"## {test.display} ({test.code})")

            for value in test.values:
                line = f"- {value.display}: "

                if value.value is not None:
                    if value.unit:
                        line += f"{value.value} {value.unit}"
                    else:
                        line += str(value.value)
                else:
                    line += "No value"

                # Add reference range
                if value.reference_range_text:
                    line += f" (Ref: {value.reference_range_text})"
                elif value.reference_range_low is not None or value.reference_range_high is not None:
                    low = value.reference_range_low if value.reference_range_low is not None else ""
                    high = value.reference_range_high if value.reference_range_high is not None else ""
                    line += f" (Ref: {low}-{high})"

                # Mark abnormal
                if value.is_abnormal:
                    line += " **ABNORMAL**"

                lines.append(line)

            lines.append("")

        return "\n".join(lines)

    def _fallback_summary(self, report: LabReport) -> str:
        """Generate a basic summary when LLM is unavailable."""
        abnormal_values: list[str] = []
        normal_tests: list[str] = []

        for test in report.tests:
            has_abnormal = False
            for value in test.values:
                if value.is_abnormal:
                    has_abnormal = True
                    abnormal_values.append(f"{value.display}: {value.value} {value.unit or ''}")

            if not has_abnormal:
                normal_tests.append(test.display)

        summary_parts = []

        if abnormal_values:
            summary_parts.append(f"ABNORMAL: {', '.join(abnormal_values)}")

        if normal_tests:
            summary_parts.append(f"Normal: {', '.join(normal_tests)}")

        return " | ".join(summary_parts) if summary_parts else "Lab results processed."

    def summarize_from_extend_output(self, extend_output: dict[str, Any]) -> str:
        """Generate a summary directly from Extend AI extraction output.

        This is useful when we haven't yet converted to LabReport format.

        Args:
            extend_output: Raw output from Extend AI processor

        Returns:
            A concise clinical summary string
        """
        # Try to format the raw output for summarization
        user_prompt = f"""Please summarize the following lab results extracted from a lab report:

{self._format_extend_output(extend_output)}

Provide a brief clinical summary highlighting any abnormal findings."""

        self.llm_client.reset_messages()
        result = self.llm_client.chat(
            system_prompt=self.SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )

        if not result["success"]:
            log.warning(f"LLM summarization failed: {result['error']}")
            return "Lab results processed. Please review the full report."

        return result["content"].strip()

    def _format_extend_output(self, output: dict[str, Any]) -> str:
        """Format Extend AI output for LLM summarization."""
        import json

        # If the output has a structured format, try to format it nicely
        if "tests" in output or "results" in output:
            tests = output.get("tests") or output.get("results") or []
            lines = []
            for test in tests:
                if isinstance(test, dict):
                    name = test.get("name") or test.get("test_name") or "Unknown Test"
                    value = test.get("value") or test.get("result") or ""
                    unit = test.get("unit") or test.get("units") or ""
                    ref_range = test.get("reference_range") or test.get("ref_range") or ""
                    abnormal = test.get("abnormal") or test.get("is_abnormal") or False

                    line = f"- {name}: {value} {unit}"
                    if ref_range:
                        line += f" (Ref: {ref_range})"
                    if abnormal:
                        line += " **ABNORMAL**"
                    lines.append(line)
            return "\n".join(lines) if lines else json.dumps(output, indent=2)

        # Fall back to JSON representation
        return json.dumps(output, indent=2)
