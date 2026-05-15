"""Annotate patient-chart conditions whose ICD-10 code has expired."""

from __future__ import annotations

import json
from typing import Any

from canvas_sdk.effects import Effect, EffectType
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol

from expired_icd10_alert.helpers import (
    get_expired_codes,
    normalize_icd10_code,
)

ICD10_SYSTEMS = {"ICD-10", "http://hl7.org/fhir/sid/icd-10"}

EXPIRED_TAG = "EXPIRED"


class ExpiredICD10Annotation(BaseProtocol):
    """Tag conditions in the patient chart that use an expired ICD-10 code.

    Reads the default expired-codes list from the bundled JSON data file.
    A site can override the list at runtime with the EXPIRED_ICD10_CODES_OVERRIDE
    secret (comma-separated list of ICD-10 codes, with or without periods).
    """

    RESPONDS_TO = EventType.Name(EventType.PATIENT_CHART__CONDITIONS)

    def compute(self) -> list[Effect]:
        expired_codes = get_expired_codes(
            self.secrets.get("EXPIRED_ICD10_CODES_OVERRIDE")
        )

        payload: dict[str, list[str]] = {}
        for condition in self.event.context:
            if condition.get("entered_in_error"):
                continue
            code = self._extract_icd10_code(condition)
            if not code:
                continue
            if normalize_icd10_code(code) in expired_codes:
                payload[condition["id"]] = [EXPIRED_TAG]

        return [
            Effect(
                type=EffectType.ANNOTATE_PATIENT_CHART_CONDITION_RESULTS,
                payload=json.dumps(payload),
            )
        ]

    @staticmethod
    def _extract_icd10_code(condition: dict[str, Any]) -> str | None:
        return next(
            (
                coding.get("code")
                for coding in condition.get("codings", [])
                if coding.get("system") in ICD10_SYSTEMS
            ),
            None,
        )
