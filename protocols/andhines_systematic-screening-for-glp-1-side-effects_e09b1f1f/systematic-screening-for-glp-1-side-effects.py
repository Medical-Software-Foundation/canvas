import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientRecordSet, PatientEventRecordSet
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED, STATUS_NOT_APPLICABLE
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.value_set.v2021.encounter_performed import OfficeVisit, HomeHealthcareServices, OutpatientConsultation
from canvas_workflow_kit.value_set.v2021.medication import DiphenhydramineHydrochloride
from canvas_workflow_kit.recommendation import AssessRecommendation, InstructionRecommendation, ReferRecommendation

class GLP1ValueSet(ValueSet):
    pass

class GLP1AllergyValueSet(ValueSet):
    pass

class GLP1ClinicalTrialValueSet(ValueSet):
    pass

class GLP1SideEffectsProtocol(ClinicalQualityMeasure):
    def in_initial_population(self) -> bool:
        return True

    def in_denominator(self) -> bool:
        glp1_prescriptions = self.patient.prescriptions.find(GLP1ValueSet)
        return len(glp1_prescriptions) > 0

    def in_numerator(self) -> bool:
        glp1_discontinued = self.patient.medications.find(GLP1ValueSet).after(arrow.now().shift(days=-30))
        glp1_allergies = self.patient.allergy_intolerances.find(GLP1AllergyValueSet)
        clinical_trial = self.patient.procedures.find(GLP1ClinicalTrialValueSet)
        if len(glp1_discontinued) > 0 or len(glp1_allergies) > 0 or len(clinical_trial) > 0:
            return False
        return True

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if not (self.in_initial_population() and self.in_denominator()):
            result.status = STATUS_NOT_APPLICABLE
        else:
            if not self.in_numerator():
                result.status = STATUS_DUE
                result.add_narrative('Recommend systematic screening for GLP-1 medication side effects.')
                assess_recommendation = AssessRecommendation(
                    key='glp1_side_effects',
                    title='Assess GLP-1 Medication Side Effects',
                    context={'narrative': 'Conduct a systematic screening for GLP-1 medication side effects.'}
                )
                instruction_recommendation = InstructionRecommendation(
                    key='glp1_adjustment',
                    title='Adjust GLP-1 Medication',
                    instructions='Evaluate severity of side effects and adjust medication if necessary.',
                    context={'narrative': 'Adjust GLP-1 medication based on side effect evaluation.'}
                )
                refer_recommendation = ReferRecommendation(
                    key='glp1_specialist',
                    title='Refer to Specialist',
                    referral=OutpatientConsultation,
                    context={'narrative': 'Refer to specialist if severe side effects are identified.'}
                )
                result.add_recommendation(assess_recommendation)
                result.add_recommendation(instruction_recommendation)
                result.add_recommendation(refer_recommendation)
            else:
                result.status = STATUS_SATISFIED
                result.add_narrative('GLP-1 medication side effects are being monitored appropriately.')
        return result