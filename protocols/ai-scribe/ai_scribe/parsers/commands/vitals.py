import re
from typing import Any, Sequence

from ai_scribe.parsers.base import CommandParser, ParsedContent

from canvas_sdk.commands.commands.vitals import VitalsCommand


class VitalsParser(CommandParser):
    """Parses the vitals section of a transcript."""

    def parse_height(self, height_str: str) -> int | None:
        """Parses height in the format 5'10" and converts it to inches."""
        match = re.search(r"(\d+)'(\d+)\"", height_str)

        if not match:
            return None

        feet = int(match.group(1))
        inches = int(match.group(2))

        return feet * 12 + inches

    def parse_weight(self, weight_str: str) -> int | None:
        """Parses weight in lbs."""
        match = re.search(r"(\d+) lbs", weight_str)

        if not match:
            return None

        return int(match.group(1))

    def parse_blood_pressure(self, bp_str: str) -> dict[str, int]:
        """Parses blood pressure in the format 167/106 and returns systole and diastole."""
        match = re.search(r"(\d+)/(\d+)", bp_str)
        if match:
            return {
                "blood_pressure_systole": int(match.group(1)),
                "blood_pressure_diastole": int(match.group(2)),
            }
        return {}

    def parse(self, content: ParsedContent, context: Any = None) -> Sequence[VitalsCommand]:
        """Parses the plan section of a transcript."""
        result: dict[str, Any] = {
            "height": None,
            "weight_lbs": None,
            "weight_oz": None,
            "blood_pressure_systole": None,
            "blood_pressure_diastole": None,
            "pulse": None,
            "oxygen_saturation": None,
        }

        vitals = content["arguments"]

        for vital in vitals:
            if "Weight" in vital:
                weight_value = self.parse_weight(vital)
                if weight_value is not None:
                    result["weight_lbs"] = weight_value

            elif "Height" in vital:
                height_value = self.parse_height(vital)
                if height_value is not None:
                    result["height"] = height_value

            elif "Blood pressure" in vital:
                bp_values = self.parse_blood_pressure(vital)
                result.update(bp_values)

            elif "Heart rate" in vital:
                match = re.search(r"(\d+)", vital)
                if match:
                    result["pulse"] = int(match.group(1))

            elif "Oxygen saturation" in vital:
                match = re.search(r"(\d+)", vital)
                if match:
                    result["oxygen_saturation"] = int(match.group(1))

        return [VitalsCommand(**result)]
