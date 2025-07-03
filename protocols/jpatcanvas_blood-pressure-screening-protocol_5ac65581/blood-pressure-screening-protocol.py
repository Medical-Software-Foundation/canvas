import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientRecordSet, PatientEventRecordSet
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED, STATUS_NOT_APPLICABLE
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.recommendation import AssessRecommendation, InstructionRecommendation, ReferRecommendation
from canvas_workflow_kit.value_set.v2022 import DiagnosisOfHypertension, PharmacologicTherapyForHypertension, EncounterToScreenForBloodPressure
from canvas_workflow_kit.value_set.v2020 import AntiHypertensivePharmacologicTherapy

class HypertensionProtocol(ClinicalQualityMeasure):
    def in_initial_population(self) -> bool:
        return bool(self.patient.is_male and 18 <= self.patient.age_at(self.now) <= 39)

    def in_denominator(self) -> bool:
        one_year_ago = self.now.shift(years=-1)
        bp_screenings = self.patient.procedures.find(EncounterToScreenForBloodPressure).after(one_year_ago)
        return len(bp_screenings) == 0

    def in_numerator(self) -> bool:
        no_hypertension = len(self.patient.conditions.find(DiagnosisOfHypertension)) == 0
        no_meds = len(self.patient.medications.find(PharmacologicTherapyForHypertension)) == 0
        no_secondary_cause = True  # Assume no secondary cause for simplicity
        not_hospitalized = len(self.patient.inpatient_stays) == 0
        not_terminal = True  # Assume not terminal for simplicity
        return bool(no_hypertension and no_meds and no_secondary_cause and not_hospitalized and not_terminal)

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        result.status = STATUS_DUE

        # No Hypertension
        if len(self.patient.conditions.find(DiagnosisOfHypertension)) == 0:
            assess_recommendation = AssessRecommendation(
                key='hypertension_assess',
                title='Assess for Hypertension',
                context={'narrative': 'Evaluate for hypertension based on blood pressure reading.'},
                patient=self.patient
            )
            result.add_recommendation(assess_recommendation)

        # No Meds
        if len(self.patient.medications.find(PharmacologicTherapyForHypertension)) == 0:
            instruction_recommendation = InstructionRecommendation(
                key='lifestyle_modification',
                title='Lifestyle Modification Counseling',
                narrative='Provide counseling on lifestyle modifications to manage elevated blood pressure.',
                patient=self.patient
            )
            result.add_recommendation(instruction_recommendation)

        # No Secondary Cause
        if True:  # Assume no secondary cause for simplicity
            refer_recommendation = ReferRecommendation(
                key='refer_evaluation',
                title='Refer for Hypertension Evaluation',
                referral=DiagnosisOfHypertension,
                condition=DiagnosisOfHypertension,
                patient=self.patient
            )
            result.add_recommendation(refer_recommendation)

        # Not Hospitalized
        if len(self.patient.inpatient_stays) == 0:
            instruction_recommendation = InstructionRecommendation(
                key='document_actions',
                title='Document Actions in EHR',
                narrative='Document all actions taken regarding blood pressure management in the EHR.',
                patient=self.patient
            )
            result.add_recommendation(instruction_recommendation)

        # Not Terminal
        if True:  # Assume not terminal for simplicity
            instruction_recommendation = InstructionRecommendation(
                key='compliance_guidelines',
                title='Ensure Compliance with Guidelines',
                narrative='Ensure compliance with the US Preventive Services Task Force guidelines for blood pressure management.',
                patient=self.patient
            )
            result.add_recommendation(instruction_recommendation)

        return result