#Clincians who code protocol
# written by A. Mathy
from canvas_workflow_kit.protocol import (
    ClinicalQualityMeasure,
    ProtocolResult,
    STATUS_DUE,
    STATUS_SATISFIED
)

from canvas_workflow_kit.constants import CHANGE_TYPE
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.recommendation import Recommendation
from canvas_workflow_kit.recommendation import InstructionRecommendation


class SeizureInstruction(ValueSet):
    VALUE_SET_NAME = 'first seizure instruction'
    SNOMEDCT = {'91175000'}

class FirstSeizure(ValueSet):
    VALUE_SET_NAME='First seizure'
    SNOMEDCT ={'371114002'}
    ICD10={'G4089'}

class FirstSeizureProtocol(ClinicalQualityMeasure):

    class Meta:

        title = 'First unprovoked seizure protocol'

        description = 'Protocol follows AAN guidelines for a first seizure'

        version = '2024-08-03v4'

        information = 'https://docs.canvasmedical.com'

        identifiers = ['NEURO-1stseizure']

        types = ['CQM']

        compute_on_change_types = [
            CHANGE_TYPE.CONDITION, CHANGE_TYPE.INSTRUCTION
        ]

        references = [
            'Protocol Reference https://www.aan.com/Guidelines/home/GuidelineDetail/687'
        ]



    def in_denominator(self):
        """
        Patients in the initial population.
        """
        return (len(self.patient.conditions.find(FirstSeizure))>0)

    def in_numerator(self):
        """
        Patients that have already been instructed
        """
        return (len(self.patient.instructions.find(SeizureInstruction))>0)


    def compute_results(self):
        result = ProtocolResult()

        if self.in_denominator():
            if self.in_numerator():
                result.status = STATUS_SATISFIED
                result.add_narrative(
                    f'{self.patient.first_name} has been given first seizure advice'
                )
            else:
                result.status = STATUS_DUE
                result.due_in = -1
                result.add_narrative(
                    f'{self.patient.first_name} needs first seizure advice'
                )

                instruction_recommendation = InstructionRecommendation(
                key='RECOMMEND_DISCUSS_SEIZURE',
                rank=1,
                button='Instruct',
                patient=self.patient,
                instruction=SeizureInstruction,
                title='Discuss risk of seizure recurrence',
                narrative="Tell patient risk of recurrence greatest within first 2 years (21-45%)."
                )
                result.add_recommendation(instruction_recommendation)
                result.add_narrative(instruction_recommendation.narrative)

        return result





