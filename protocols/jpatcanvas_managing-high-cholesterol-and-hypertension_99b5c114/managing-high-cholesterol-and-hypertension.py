import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientRecordSet, PatientPeriodRecordSet
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED, STATUS_NOT_APPLICABLE
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.recommendation import Recommendation, LabRecommendation, PrescribeRecommendation
from canvas_workflow_kit.value_set.v2022 import (
    IschemicHeartDiseaseOrOtherRelatedDiagnoses,
    CounselingForNutrition,
    ReferralOrCounselingForAlcoholConsumption,
    CounselingForPhysicalActivity,
    FamilialHypercholesterolemia,
    StatinAllergen,
    Pregnancy,
    Breastfeeding,
    ImmunocompromisedConditions
)

class CardiovascularRiskProtocol(ClinicalQualityMeasure):
    def in_initial_population(self) -> bool:
        return bool(18 <= self.patient.age_at(self.now) <= 50)

    def in_denominator(self) -> bool:
        family_history = len(self.patient.conditions.find(IschemicHeartDiseaseOrOtherRelatedDiagnoses)) > 0
        diet = len(self.patient.interviews.find(CounselingForNutrition)) > 0
        alcohol = len(self.patient.interviews.find(ReferralOrCounselingForAlcoholConsumption)) > 0
        sedentary = len(self.patient.interviews.find(CounselingForPhysicalActivity)) > 0
        return family_history and diet and alcohol and sedentary

    def in_numerator(self) -> bool:
        hyperlipidemia = len(self.patient.conditions.find(FamilialHypercholesterolemia)) > 0
        contraindications = len(self.patient.allergy_intolerances.find(StatinAllergen)) > 0
        pregnant = self.patient.is_female and len(self.patient.conditions.find(Pregnancy)) > 0
        breastfeeding = self.patient.is_female and len(self.patient.conditions.find(Breastfeeding)) > 0
        comorbid = len(self.patient.conditions.find(ImmunocompromisedConditions)) > 0
        return not (hyperlipidemia or contraindications or pregnant or breastfeeding or comorbid)

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if not (self.in_initial_population() and self.in_denominator()):
            result.status = STATUS_NOT_APPLICABLE
        else:
            if self.in_numerator():
                result.status = STATUS_SATISFIED
                result.add_narrative('Patient is eligible for cardiovascular risk management.')
            else:
                result.status = STATUS_DUE
                result.add_narrative('Patient is not eligible for cardiovascular risk management.')
                if len(self.patient.conditions.find(FamilialHypercholesterolemia)) > 0:
                    result.add_narrative('Patient has hyperlipidemia.')
                    statin_recommendation = PrescribeRecommendation(
                        key='statin',
                        prescription=StatinAllergen,
                        title='Prescribe Statin',
                        narrative='Recommend prescribing statin to manage hyperlipidemia.',
                        patient=self.patient
                    )
                    result.add_recommendation(statin_recommendation)
                if len(self.patient.allergy_intolerances.find(StatinAllergen)) > 0:
                    result.add_narrative('Patient has contraindications to statin therapy.')
                if self.patient.is_female and len(self.patient.conditions.find(Pregnancy)) > 0:
                    result.add_narrative('Patient is pregnant.')
                if self.patient.is_female and len(self.patient.conditions.find(Breastfeeding)) > 0:
                    result.add_narrative('Patient is breastfeeding.')
                if len(self.patient.conditions.find(ImmunocompromisedConditions)) > 0:
                    result.add_narrative('Patient has severe comorbid conditions.')
        return result