from canvas_workflow_kit.protocol import (
    ClinicalQualityMeasure,
    ProtocolResult,
    STATUS_DUE,
    STATUS_SATISFIED
)

from canvas_workflow_kit.constants import CHANGE_TYPE
from canvas_workflow_kit.recommendation import InstructionRecommendation
from canvas_workflow_kit.value_set.value_set import ValueSet
from canvas_workflow_kit.timeframe import Timeframe

class TSSurgery(ValueSet):
    VALUE_SET_NAME = "Transsphenoidal Surgery"
    OID = "1"
    EXPANSION_VERSION = "fixing erroneous code"
    ICD10PCS = {
        '0BBH0ZZ',
        '0BBH3ZZ',
        '0BBH4ZZ',
        '0BBH8ZZ',
        '0BBJ0ZZ',
        '0BBJ3ZZ',
        '0BBJ4ZZ',
        '0BBJ8ZZ'
    }

    SNOMEDCT = {
        '46296006',
        '82421004',
        '53158000',
        '67598004',
        '276274008',
        '446813000',
        '446814006',
        '726755001',
        '726756000',
        '23676000'
    }

    CPT = {
        '62165',
        '61548'
    }

class FluidRestriction(ValueSet):
    VALUE_SET_NAME = "Fluid Restriction 1L/day"
    SNOMEDCT = {
        '710743006'  # Fluid restriction regimen
    }

class SIADH_PVN_POST_TSS(ClinicalQualityMeasure):

    class Meta:

        title = 'SIADH Prevention Protocol following Transsphenoidal surgery'

        description = 'The protocol Ed Laws published to prevent SIADH in post-op TSS patients'

        version = '1'

        information = 'Instruct the patient to restrict fluids to 1L for 7 days following transsphenoidal surgery. ' \
                      'This has been proven to prevent SIADH in patients post-surgery.'

        identifiers = ['CMS12345v1']

        types = ['CQM']

        compute_on_change_types = [
            CHANGE_TYPE.CONDITION,
            CHANGE_TYPE.INSTRUCTION
        ]

        references = [
            'Protocol Reference https://pubmed.ncbi.nlm.nih.gov/29075986/'
        ]


    def in_denominator(self):
        """
        Patients who have had the surgery.
        """
        return self.patient.conditions.find(TSSurgery)

    def in_numerator(self):
        """
        Patients who have had the surgery in the window of intervention and does not have water restriction instruction.
        """
        last_TS_surgery_timeframe = Timeframe(self.now.shift(days=-100), self.now)

        water_restriction_present = self.patient.instructions.find(FluidRestriction)

        context_conditions = ((self.patient.conditions.find(TSSurgery).intersects(
            last_TS_surgery_timeframe, still_active=self.patient.active_only)) and not water_restriction_present)

        # Return True if TSSurgery is found in conditions within the timeframe and water restriction isnt true
        return bool(context_conditions)

    def compute_results(self):
        result = ProtocolResult()

        if self.in_denominator():  # if they have had TSS
            if self.in_numerator():  # If they had TSS in last 7 days (otherwise they are outside the window)
                result.status = STATUS_DUE
                result.due_in = -1

                fluid_restriction_instruction = InstructionRecommendation(
                        key='INSTRUCT_WATER_RESTRICTION',
                        rank=1,
                        button="Instruct",
                        patient=self.patient,
                        instruction=FluidRestriction,
                        title=f'Suggest fluid restriction',
                        narrative='restrict fluid intake to 1 liter per day for 7 days after surgery'
                    )

                result.add_recommendation(fluid_restriction_instruction)
                result.add_narrative(fluid_restriction_instruction.narrative)
        return result
