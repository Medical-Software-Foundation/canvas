from canvas_workflow_kit.protocol import (
    ClinicalQualityMeasure,
    ProtocolResult,
    STATUS_DUE,
    STATUS_SATISFIED,
)

from canvas_workflow_kit.constants import CHANGE_TYPE
from canvas_workflow_kit.recommendation import InstructionRecommendation
from canvas_workflow_kit.value_set import ValueSet

version_number = "0.0012"


class OSAHS(ValueSet):
    VALUE_SET_NAME = "Obstructive Sleep Apnoea Hypopnoea Syndrome"
    ICD10CM = {"G4733"}
    SNOMEDCT = {"101301000119106"}


class CPAPRecommndation(ValueSet):
    VALUE_SET_NAME = "Recommend CPAP"
    SNOMEDCT = {"702172008"}


class SleepApnoeaOfferCPAP(ClinicalQualityMeasure):
    class Meta:

        title = (
            "Obstructive Sleep Apnoea Hypopnoea Syndrome CPAP Recommendation"
        )

        description = (
            "Assesses if a patient should be offered CPAP for obstructive "
            "sleep apnoea hypopnoea syndrome"
        )

        version = version_number

        information = "https://docs.canvasmedical.com"

        identifiers = ["G4733"]

        types = ["CQM"]

        compute_on_change_types = [
            CHANGE_TYPE.CONDITION,
            CHANGE_TYPE.LAB_REPORT,
            CHANGE_TYPE.INSTRUCTION,
        ]

        references = [
            "Protocol Reference https://www.nice.org.uk/guidance/ng202/resources/visual-summary-on-osahs-investigations-and-treatment-pdf-9204628717"
        ]

    def in_denominator(self) -> bool:
        """
        Patients in the initial population.
        """
        # Check if the patient has a diagnosis of OSAHS
        if self.patient.conditions.find(OSAHS):
            return True

        return False

    def in_numerator(self) -> bool:
        """
        Patients that have already been notified.
        """
        if self.patient.instructions.find(CPAPRecommndation):
            return True

        return False

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()

        if self.in_denominator():
            if self.in_numerator():
                result.status = STATUS_SATISFIED
                result.add_narrative(
                    f"{self.patient.first_name} has already been offered CPAP."
                )
            else:
                result.status = STATUS_DUE
                result.due_in = -1
                result.add_narrative(
                    f"{self.patient.first_name} should be offered CPAP treatment."
                )

                result.add_recommendation(
                    InstructionRecommendation(
                        key="CPAP_offer",
                        rank=1,
                        button="Instruct",
                        patient=self.patient,
                        instruction=CPAPRecommndation,
                        title="Offer CPAP",
                        narrative="Offer CPAP treatment to the patient",
                    )
                )
        return result
