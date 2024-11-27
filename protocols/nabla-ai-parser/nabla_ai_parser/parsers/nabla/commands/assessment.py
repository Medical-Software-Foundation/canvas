from typing import Any, Sequence

from nabla_ai_parser.parsers.base import CommandParser, ParsedContent
from rapidfuzz import fuzz, process, utils

from canvas_sdk.commands.commands.assess import AssessCommand
from canvas_sdk.commands.commands.diagnose import DiagnoseCommand
from canvas_sdk.v1.data import Condition
from canvas_sdk.value_set.value_set import CodeConstants


class AssessmentParser(CommandParser):
    """Parses the assessment section of a Nabla transcript."""

    def parse(
        self, content: ParsedContent, context: dict[str, Any] | None = None
    ) -> Sequence[DiagnoseCommand | AssessCommand]:
        """Parses the plan section of a Nabla transcript."""
        icd_10_codes: list[dict[str, str]] = content.get("extra", {}).get("icd_10_codes", [])
        output: list[DiagnoseCommand | AssessCommand] = []

        if not icd_10_codes:
            return output

        if not context or "patient" not in context:
            return output

        patient_id = context["patient"]["id"]
        patient_condition_codes = {
            coding.code: str(condition.id)
            for condition in Condition.objects.for_patient(patient_id).committed()
            for coding in condition.codings.filter(system=CodeConstants.URL_ICD10)[:1]
            if coding
        }

        choices = [code["text"] for code in icd_10_codes]

        for line in content["arguments"]:
            condition, *comments = line.split(",")
            narrative = "".join(comments).strip()
            result = process.extractOne(
                condition, choices, scorer=fuzz.partial_ratio, processor=utils.default_process
            )

            if result and result[1] == 100:
                icd_10_coding = icd_10_codes[result[2]]
                icd_10_code = icd_10_coding["code"].replace(".", "")
                if icd_10_code in patient_condition_codes:
                    output.append(
                        AssessCommand(
                            condition_id=patient_condition_codes[icd_10_code],
                            narrative=narrative,
                        )
                    )
                else:
                    output.append(
                        DiagnoseCommand(icd10_code=icd_10_code, today_assessment=narrative)
                    )

        return output
