import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientRecordSet, PatientEventRecordSet
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED, STATUS_NOT_APPLICABLE
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.recommendation import AssessRecommendation, LabRecommendation
from canvas_workflow_kit.value_set.v2021.medication import DiphenhydramineHydrochloride
from canvas_workflow_kit.value_set.v2020 import AnnualWellnessVisit as AWV2020
from canvas_workflow_kit.value_set.v2021.encounter import AnnualWellnessVisit as AWV2021
from canvas_workflow_kit.value_set.v2021.encounter_performed import OfficeVisit

class SerotoninMedications(ValueSet):
    pass

class SerotoninSyndrome(ValueSet):
    pass

class SerotoninSyndromeProtocol(ClinicalQualityMeasure):
    def in_initial_population(self) -> bool:
        prescribed_meds = self.patient.medications.find(SerotoninMedications)
        return len(prescribed_meds) > 0

    def in_denominator(self) -> bool:
        additional_meds = self.patient.medications.find(DiphenhydramineHydrochloride)
        no_history_ss = len(self.patient.conditions.find(SerotoninSyndrome)) == 0
        stable_regimen = len(additional_meds) > 0
        return len(additional_meds) > 0 and no_history_ss and stable_regimen

    def in_numerator(self) -> bool:
        med_review_done = len(self.patient.interviews.find(SerotoninSyndrome)) > 0
        clinical_assessment_done = len(self.patient.procedures.find(AWV2020 | AWV2021 | OfficeVisit)) > 0
        lab_tests_done = len(self.patient.lab_reports.find(SerotoninSyndrome)) > 0
        return med_review_done and clinical_assessment_done and lab_tests_done

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if not (self.in_initial_population() and self.in_denominator()):
            result.status = STATUS_NOT_APPLICABLE
        else:
            if self.in_numerator():
                result.status = STATUS_SATISFIED
                result.add_narrative('Patient has completed the serotonin syndrome screening.')
            else:
                result.status = STATUS_DUE
                result.add_narrative('Patient requires serotonin syndrome screening.')
                med_review_recommendation = AssessRecommendation(
                    key='med_review',
                    title='Conduct Medication Review',
                    narrative='Perform a comprehensive medication review to identify potential drug interactions.',
                    patient=self.patient
                )
                clinical_assessment_recommendation = AssessRecommendation(
                    key='clinical_assessment',
                    title='Conduct Clinical Assessment',
                    narrative='Perform a clinical assessment for symptoms of serotonin syndrome.',
                    patient=self.patient
                )
                lab_tests_recommendation = LabRecommendation(
                    key='lab_tests',
                    title='Order Laboratory Tests',
                    narrative='Order laboratory tests to rule out other causes of symptoms.',
                    patient=self.patient,
                    lab=SerotoninSyndrome
                )
                result.add_recommendation(med_review_recommendation)
                result.add_recommendation(clinical_assessment_recommendation)
                result.add_recommendation(lab_tests_recommendation)
        return result