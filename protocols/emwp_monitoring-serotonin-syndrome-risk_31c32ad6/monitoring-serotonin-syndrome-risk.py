import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientRecordSet, PatientEventRecordSet
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED, STATUS_NOT_APPLICABLE
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.value_set.v2021.encounter import BehavioralHealthFollowUpVisit
from canvas_workflow_kit.value_set.v2021.encounter_performed import OfficeVisit
from canvas_workflow_kit.recommendation import DiagnoseRecommendation, InstructionRecommendation, FollowUpRecommendation

class SerotoninSyndromeMeasure(ClinicalQualityMeasure):
    class SerotonergicMedications(ValueSet):
        pass

    class InteractingMedications(ValueSet):
        pass

    class SerotoninSyndromeDiagnosis(ValueSet):
        pass

    def in_initial_population(self) -> bool:
        prescribed_meds = self.patient.medications.find(self.SerotonergicMedications)
        return len(prescribed_meds) > 0

    def in_denominator(self) -> bool:
        interacting_meds = self.patient.medications.find(self.InteractingMedications)
        return len(interacting_meds) > 0

    def in_numerator(self) -> bool:
        history_of_syndrome = self.patient.conditions.find(self.SerotoninSyndromeDiagnosis)
        discontinued_meds = self.patient.medications.find(self.SerotonergicMedications).before(arrow.now().shift(days=-30))
        palliative_care = self.patient.conditions.find(self.SerotoninSyndromeDiagnosis)
        if len(history_of_syndrome) > 0 or len(discontinued_meds) > 0 or len(palliative_care) > 0:
            return False

        med_review = self.patient.medications.find(self.InteractingMedications)
        clinical_assessment = self.patient.conditions.find(self.SerotoninSyndromeDiagnosis)
        lab_tests = self.patient.lab_reports.find(self.SerotoninSyndromeDiagnosis)
        if len(med_review) > 0 and len(clinical_assessment) > 0 and len(lab_tests) > 0:
            address_interactions = self.patient.medications.find(self.InteractingMedications)
            if len(address_interactions) > 0:
                return True
        return False

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if not (self.in_initial_population() and self.in_denominator()):
            result.status = STATUS_NOT_APPLICABLE
        else:
            if self.in_numerator():
                result.status = STATUS_SATISFIED
                result.add_narrative('Serotonin syndrome risk successfully managed.')
            else:
                result.status = STATUS_DUE
                result.add_narrative('Serotonin syndrome risk requires further management.')
                result.add_recommendation(DiagnoseRecommendation(
                    key='med_review',
                    title='Conduct Medication Review',
                    narrative='Perform a comprehensive medication review to identify potential drug interactions.',
                    condition=self.SerotoninSyndromeDiagnosis,
                    action='review'
                ))
                result.add_recommendation(DiagnoseRecommendation(
                    key='clinical_assessment',
                    title='Conduct Clinical Assessment',
                    narrative='Perform a clinical assessment for symptoms of serotonin syndrome.',
                    condition=self.SerotoninSyndromeDiagnosis,
                    action='assess'
                ))
                result.add_recommendation(DiagnoseRecommendation(
                    key='lab_tests',
                    title='Order Laboratory Tests',
                    narrative='Order laboratory tests to rule out other causes of symptoms.',
                    condition=self.SerotoninSyndromeDiagnosis,
                    action='test'
                ))
                result.add_recommendation(InstructionRecommendation(
                    key='address_interactions',
                    title='Address Drug Interactions',
                    narrative='Adjust or discontinue medications to address potential drug interactions.',
                    patient=self.patient
                ))
                result.add_recommendation(InstructionRecommendation(
                    key='patient_education',
                    title='Provide Patient Education',
                    narrative='Educate the patient about the signs and symptoms of serotonin syndrome.',
                    instruction=BehavioralHealthFollowUpVisit
                ))
                result.add_recommendation(FollowUpRecommendation(
                    key='follow_up',
                    title='Schedule Follow-Up',
                    narrative='Schedule follow-up assessments to monitor for the development of symptoms.',
                    instruction=OfficeVisit
                ))
        return result