from canvas_workflow_kit.protocol import (
    ClinicalQualityMeasure,
    ProtocolResult,
    STATUS_DUE,
    STATUS_SATISFIED
)

from canvas_workflow_kit.constants import CHANGE_TYPE
from canvas_workflow_kit.recommendation import InstructionRecommendation, HyperlinkRecommendation
from canvas_workflow_kit.value_set import ValueSet


class Concussion(ValueSet):
    VALUE_SET_NAME = 'Concussion'
    SNOMEDCT = {'404684003'}
    ICD10CM = {'S060X0A'}

class ConcussionRTPInstructions(ValueSet):
    """

    Clinical Focus: Sports Medicine
    Data Element Scope:
    Inclusion Criteria: Patients with a diagnosis of concussion
    Exclusion Criteria:
    """

    OID = 'pending'
    VALUE_SET_NAME = 'Concussion RTP Instructions'
    EXPANSION_VERSION = 'pending'

    SNOMEDCT = {'229191008'}


class ReturnToPlayConcussion(ClinicalQualityMeasure):

    class Meta:

        title = 'Concussion: Return to Play Protocol'

        description = 'Protocol to initiate the return to play protocol for patients with concussions.'

        version = '2024-03-11v1.1'

        information = 'https://docs.canvasmedical.com'

        identifiers = ['Neuro-ConcussionRTP']

        types = ['CQM']

        compute_on_change_types = [
            CHANGE_TYPE.CONDITION,
            CHANGE_TYPE.INSTRUCTION
        ]
            

        references = [
            'Protocol Reference https://www.cdc.gov/headsup/pdfs/providers/return_to_activities.pdf'
        ]


    def in_denominator(self):
        """
        Patients with diagnosis of Concussion
        """
        return (len(self.patient.conditions.find(Concussion))>0)

    def in_numerator(self):
        """
        Has patients been instructed on RTP.
        """
        return (len(self.patient.instructions.find(ConcussionRTPInstructions))>0) 

    def compute_results(self):
        result = ProtocolResult()

        if self.in_denominator():
            if self.in_numerator():
                result.status = STATUS_SATISFIED
                result.add_narrative(
                    f'{self.patient.first_name} RTP Protocol Initiated'
                )
            else:
                result.status = STATUS_DUE
                result.due_in = -1
                result.add_narrative(f'{self.patient.first_name} has been diagnosed with a concussion. If patient in sports. Initiate Return to Play Protocol.')

            concussion_instruction_recs=InstructionRecommendation(
                key='CONCUSSION_RTP_PROTOCOL',
                rank=1,
                patient=self.patient,
                instruction=ConcussionRTPInstructions,
                title='Initiate Return to Play Protocol',
                narrative="""Patient to follow 5 step return to play protocol. 
                1. No activity, 2. Light aerobic exercise, 3. Sport specific exercise, 
                4. Non-contact training drills, 5. Full contact practice."""
            )
              
            hyperlink_recommendation = HyperlinkRecommendation(
                key='PROTOCOL_DOCUMENTATION_LINK',
                rank=2,
                button='For Detailed CDC Guidelines',
                href='https://www.cdc.gov/headsup/basics/return_to_sports.html',
                title='CDC Guidelines for Concussion Return to Play Protocol'
            )
        
            result.add_recommendation(concussion_instruction_recs) 
            result.add_recommendation(hyperlink_recommendation)    
                       
        return result
