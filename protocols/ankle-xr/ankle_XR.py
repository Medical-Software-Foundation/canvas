from canvas_workflow_kit.protocol import (
    ClinicalQualityMeasure,
    ProtocolResult,
    STATUS_DUE,
    STATUS_SATISFIED
)

from canvas_workflow_kit.constants import CHANGE_TYPE
from canvas_workflow_kit.recommendation import InstructionRecommendation, ImagingRecommendation
from canvas_workflow_kit.value_set import ValueSet


class AnkleInjury(ValueSet):
    VALUE_SET_NAME = 'Ankle Injury'
    SNOMEDCT = {'404684003'}
    ICD10CM = {'S93402A'}

class AnkleXR2V(ValueSet):
    """

    Clinical Focus:
    Data Element Scope:
    Inclusion Criteria:
    Exclusion Criteria:
    """

    OID = 'pending'
    VALUE_SET_NAME = 'XR Ankle 2 Views'
    EXPANSION_VERSION = 'pending'

    CPT = {'73600'}

    SNOMEDCT = {'19490002'}

class AnkleInjuryInstructions(ValueSet):

    VALUE_SET_NAME = 'Ankle Injury Rehab'
   
    SNOMEDCT = {'229191008'}

class AnkleInjuryXR(ClinicalQualityMeasure):

    class Meta:

        title = 'Ankle Injury: X-Ray Utilization'

        description = 'Protocol to identify patients with ankle injuries who have should recieve an X-Ray'

        version = '2024-03-11v2.0'

        information = 'https://docs.canvasmedical.com'

        identifiers = ['MSK-ankleinjuryXR']

        types = ['CQM']

        compute_on_change_types = [
            CHANGE_TYPE.CONDITION,
            CHANGE_TYPE.INSTRUCTION
        ]
            

        references = [
            'Protocol Reference https://upload.orthobullets.com/journalclub/pubmed_central/8616287.pdf'
        ]


    def in_denominator(self):
        """
        Patients with diagnosis of Ankle Injury
        """
        return (len(self.patient.conditions.find(AnkleInjury))>0)

    def in_numerator(self):
        """
        Have patients been X-rayed or not.
        """
        return (len(self.patient.instructions.find(AnkleInjuryInstructions))>0) 

    def compute_results(self):
        result = ProtocolResult()

        if self.in_denominator():
            if self.in_numerator():
                result.status = STATUS_SATISFIED
                result.add_narrative(
                    f'{self.patient.first_name} Ankle XR has been ordered'
                )
            else:
                result.status = STATUS_DUE
                result.due_in = -1
                result.add_narrative(f'If {self.patient.first_name} has pain in areas of Ottawa rules, then he/she may need an Ankle XR')

                ankle_imaging=ImagingRecommendation(
                    key='MSK-ankleinjuryXR',
                    rank=2,
                    button='Order Ankle X-Ray',
                    patient=self.patient,
                    imaging=AnkleXR2V,
                    title='Order Ankle X-Ray(2-views)'
                    )
                
                ankle_rehab_instructions=InstructionRecommendation(
                    key='ANKLE_REHAB_INSTRUCTIONS',
                    rank=1,
                    patient=self.patient,
                    instruction=AnkleInjuryInstructions,
                    title='Educate and Order XR Below',
                    narrative='Patient to follow ankle rehab program and proceed with Ankle XR'
                    )
                
                result.add_recommendation(ankle_rehab_instructions)
                result.add_recommendation(ankle_imaging)

        return result
