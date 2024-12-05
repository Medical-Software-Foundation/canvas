import re
from typing import Any

from ai_scribe.parsers.base import (
    ParsedContent,
    TranscriptParser,
    TranscriptParserOutput,
)
from ai_scribe.parsers.commands.assessment import (
    AssessmentParser,
)
from ai_scribe.parsers.commands.history_present_illness import (
    HistoryPresentIllnessParser,
)
from ai_scribe.parsers.commands.past_medical_history import (
    PastMedicalHistoryParser,
)
from ai_scribe.parsers.commands.plan import PlanParser
from ai_scribe.parsers.commands.reason_for_visit import (
    ReasonForVisitParser,
)
from ai_scribe.parsers.commands.vitals import VitalsParser


class ScribeParser(TranscriptParser):
    """An example parser for AI scribe transcripts."""

    section_parsers = {
        "plan": PlanParser(),
        "vitals": VitalsParser(),
        "chief_complaint": ReasonForVisitParser(),
        "history_of_present_illness": HistoryPresentIllnessParser(),
        "past_medical_history": PastMedicalHistoryParser(),
        "assessment": AssessmentParser(),
    }

    def parse_icd10_section(self, icd10_lines: list) -> list[dict[str, str]]:
        """Parse ICD-10 codes section into a list of dictionaries."""
        icd10_list = []

        for line in icd10_lines:
            # Match lines that follow the format '- Description [Code]'
            match = re.match(r"-?\s*(.+?)\s*\[([A-Z0-9.]+)\]", line.strip())

            if match:
                text, code = match.groups()
                icd10_list.append({"code": code, "text": text})

        return icd10_list

    def parse(
        self,
        transcript: str,
        context: Any | None = None,
    ) -> TranscriptParserOutput:
        """Parses the given transcript and returns a dictionary of Commands."""
        parsed_data: dict = {}
        sections = self.parse_sections(transcript)

        for section_name, content in sections.items():
            if section_name in self.section_parsers:
                parsed_data[section_name] = self.section_parsers[section_name].parse(
                    content, context
                )

        return parsed_data

    def parse_sections(self, transcript: str) -> dict[str, ParsedContent]:
        """Parses the given transcript and returns a dictionary of sections."""
        sections = re.split(r"\n\s*\n", transcript.strip())
        parsed_data = {}

        for section in sections:
            lines = section.strip().split("\n")
            header = lines[0].strip().lower()
            header = "icd_10_codes" if "icd-10" in header else header.replace(" ", "_")

            arguments = [re.sub(r"^[-•\d.]+\s*", "", line).strip() for line in lines[1:]]

            parsed_data[header] = (
                ParsedContent(arguments=self.parse_icd10_section(lines[1:]))
                if header == "icd_10_codes"
                else ParsedContent(arguments=arguments)
            )

        if "icd_10_codes" in parsed_data:
            icd_codes = parsed_data.pop("icd_10_codes")["arguments"]
            for section in parsed_data:
                # Merge the ICD-10 codes with the existing section
                parsed_data[section] = ParsedContent(
                    arguments=parsed_data[section]["arguments"], extra={"icd_10_codes": icd_codes}
                )

        return parsed_data
