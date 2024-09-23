import json

from canvas_sdk.effects import Effect, EffectType
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from logger import log

# Update list with extra ICD codes as needed
# https://www.cms.gov/medicare/health-plans/medicareadvtgspecratestats/risk-adjustors/2024-model-software/icd-10-mappings
ICD_CODES = {"HCC": ["A0103", "A0104", "A0105"]}

HCC = "HCC"
CONGIDITAL_DISORDERS_CODES = "Q"
PREGNANCY_CODES = "O"
PEDIATRIC_CODES = "P"

ICD10 = "ICD-10"


class PatientChartConditionAnnotation(BaseProtocol):
    """
    Annotate Conditions in the Patient Chart with and HCC or SDOH tag
    """

    RESPONDS_TO = EventType.Name(EventType.PATIENT_CHART__CONDITIONS)

    NARRATIVE_STRING = "I will annotate conditions with an HCC tag"

    def compute(self):

        hcc_codes = ICD_CODES[HCC]

        payload = {}
        for condition in self.context:
            icd10_code = next(coding["code"] for coding in condition["codings"])
            if not icd10_code:
                continue

            if icd10_code in hcc_codes:
                payload[condition["id"]] = [HCC]

        # Return zero, one, or many effects.
        return [Effect(type=EffectType.ANNOTATE_PATIENT_CHART_CONDITION_RESULTS, payload=json.dumps(payload))]


class ClaimConditionAnnotation(BaseProtocol):
    """
    Annotate Conditions in the Claim modal with an HCC tag
    """

    RESPONDS_TO = [EventType.Name(EventType.CLAIM__CONDITIONS)]

    NARRATIVE_STRING = "I will annotate conditions with an HCC ortag"

    def compute(self):

        hcc_codes = ICD_CODES[HCC]

        payload = {}
        for condition in self.context:
            icd10_code = next(coding["code"] for coding in condition["codings"] if coding["system"] == ICD10)
            if not icd10_code:
                continue

            if icd10_code in hcc_codes:
                payload[condition["id"]] = [HCC]

        # Return zero, one, or many effects.
        return [Effect(type=EffectType.ANNOTATE_CLAIM_CONDITION_RESULTS, payload=json.dumps(payload))]