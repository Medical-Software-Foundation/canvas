from typing import Any, Sequence

from ai_scribe.parsers.base import CommandParser, ParsedContent
from rapidfuzz import fuzz, process, utils

from canvas_sdk.commands.commands.medical_history import MedicalHistoryCommand


class PastMedicalHistoryParser(CommandParser):
    """Parses the plan section of a transcript."""

    def parse(self, content: ParsedContent, context: Any = None) -> Sequence[MedicalHistoryCommand]:
        """Parses the plan section of a transcript."""
        icd_10_codes: list[dict[str, str]] = content.get("extra", {}).get("icd_10_codes", [])
        output: list[MedicalHistoryCommand] = []

        if not icd_10_codes:
            return output

        choices = [code["text"] for code in icd_10_codes]

        for line in content["arguments"]:
            result = process.extractOne(
                line, choices, scorer=fuzz.partial_ratio, processor=utils.default_process
            )

            if result and result[1] == 100:
                icd_10_code = icd_10_codes[result[2]]
                output.append(MedicalHistoryCommand(past_medical_history=icd_10_code["code"]))

        return output
