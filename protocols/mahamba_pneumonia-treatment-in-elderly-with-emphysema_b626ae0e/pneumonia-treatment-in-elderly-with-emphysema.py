import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientEventRecordSet, PatientPeriodRecordSet
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED, STATUS_NOT_APPLICABLE
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.value_set.v2021.diagnosis import AdvancedIllness, CompetingConditionsForRespiratoryConditions
from canvas_workflow_kit.value_set.v2020 import ContactOrOfficeVisit
from canvas_workflow_kit.value_set.v2021.encounter import EncounterToScreenForBloodPressure
from canvas_workflow_kit.value_set.v2021.encounter_performed import OfficeVisit
from canvas_workflow_kit.value_set.v2021.diagnosis import XRayStudyAllInclusive
from canvas_workflow_kit.recommendation import DiagnoseRecommendation, ImagingRecommendation, LabRecommendation, PrescribeRecommendation

class EmphysemaValueSet(AdvancedIllness):
    pass

class PneumoniaValueSet(CompetingConditionsForRespiratoryConditions):
    pass

class PhysicalExaminationValueSet(ContactOrOfficeVisit, EncounterToScreenForBloodPressure, OfficeVisit):
    pass

class CTScanValueSet(XRayStudyAllInclusive):
    pass

class EmphysemaPneumoniaMeasure(ClinicalQualityMeasure):
    def in_initial_population(self) -> bool:
        return bool(self.patient.age_at(arrow.now()) >= 65 and len(self.patient.conditions.find(EmphysemaValueSet)) > 0)

    def in_denominator(self) -> bool:
        symptoms = self.patient.interviews.find(PneumoniaValueSet)
        exposure = self.patient.interviews.find(PneumoniaValueSet)
        return bool(len(symptoms) > 0 or len(exposure) > 0)

    def in_numerator(self) -> bool:
        allergy = self.patient.allergy_intolerances.find(PneumoniaValueSet)
        acute_condition = self.patient.conditions.find(PneumoniaValueSet)
        end_stage_copd = self.patient.conditions.find(PneumoniaValueSet)
        if len(allergy) > 0 or len(acute_condition) > 0 or len(end_stage_copd) > 0:
            return False

        chest_xray = self.patient.imaging_reports.find(CTScanValueSet).after(arrow.now().shift(days=-30))
        cbc = self.patient.lab_reports.find(PneumoniaValueSet).after(arrow.now().shift(days=-30))
        sputum_culture = self.patient.lab_reports.find(PneumoniaValueSet).after(arrow.now().shift(days=-30))
        pulse_oximetry = self.patient.procedures.find(PneumoniaValueSet).after(arrow.now().shift(days=-30))
        ct_scan = self.patient.imaging_reports.find(CTScanValueSet).after(arrow.now().shift(days=-30))
        pneumonia_diagnosis = self.patient.conditions.find(PneumoniaValueSet).after(arrow.now().shift(days=-30))
        antibiotics = self.patient.medications.find(PneumoniaValueSet).after(arrow.now().shift(days=-30))

        return bool(
            len(chest_xray) > 0 and
            len(cbc) > 0 and
            len(sputum_culture) > 0 and
            len(pulse_oximetry) > 0 and
            len(ct_scan) > 0 and
            len(pneumonia_diagnosis) > 0 and
            len(antibiotics) > 0
        )

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        result.status = STATUS_NOT_APPLICABLE

        if not (self.in_initial_population() and self.in_denominator()):
            return result

        result.status = STATUS_DUE
        result.add_narrative('Patient presents with symptoms or exposure indicative of pneumonia.')

        allergy = self.patient.allergy_intolerances.find(PneumoniaValueSet)
        acute_condition = self.patient.conditions.find(PneumoniaValueSet)
        end_stage_copd = self.patient.conditions.find(PneumoniaValueSet)
        if len(allergy) > 0 or len(acute_condition) > 0 or len(end_stage_copd) > 0:
            result.status = STATUS_NOT_APPLICABLE
            return result

        chest_xray = self.patient.imaging_reports.find(CTScanValueSet).after(arrow.now().shift(days=-30))
        if len(chest_xray) == 0:
            result.add_recommendation(ImagingRecommendation(
                key='chest_xray',
                imaging=CTScanValueSet,
                title='Order Chest X-Ray',
                narrative='Order a chest X-ray to evaluate for pneumonia.',
                patient=self.patient
            ))

        cbc = self.patient.lab_reports.find(PneumoniaValueSet).after(arrow.now().shift(days=-30))
        if len(cbc) == 0:
            result.add_recommendation(LabRecommendation(
                key='cbc',
                lab=PneumoniaValueSet,
                title='Order CBC',
                narrative='Order a complete blood count to assess for infection.',
                patient=self.patient
            ))

        sputum_culture = self.patient.lab_reports.find(PneumoniaValueSet).after(arrow.now().shift(days=-30))
        if len(sputum_culture) == 0:
            result.add_recommendation(LabRecommendation(
                key='sputum_culture',
                lab=PneumoniaValueSet,
                title='Order Sputum Culture',
                narrative='Order a sputum culture to identify the causative organism.',
                patient=self.patient
            ))

        pulse_oximetry = self.patient.procedures.find(PneumoniaValueSet).after(arrow.now().shift(days=-30))
        if len(pulse_oximetry) == 0:
            result.add_recommendation(DiagnoseRecommendation(
                key='pulse_oximetry',
                condition=PneumoniaValueSet,
                title='Perform Pulse Oximetry',
                narrative='Perform pulse oximetry to assess oxygen saturation.',
                patient=self.patient
            ))

        ct_scan = self.patient.imaging_reports.find(CTScanValueSet).after(arrow.now().shift(days=-30))
        if len(ct_scan) == 0:
            result.add_recommendation(ImagingRecommendation(
                key='ct_scan',
                imaging=CTScanValueSet,
                title='Consider CT Scan',
                narrative='Consider a CT scan if the chest X-ray is inconclusive.',
                patient=self.patient
            ))

        pneumonia_diagnosis = self.patient.conditions.find(PneumoniaValueSet).after(arrow.now().shift(days=-30))
        if len(pneumonia_diagnosis) == 0:
            result.add_recommendation(DiagnoseRecommendation(
                key='pneumonia_diagnosis',
                condition=PneumoniaValueSet,
                title='Diagnose Pneumonia',
                narrative='Diagnose pneumonia based on clinical and radiological findings.',
                patient=self.patient
            ))

        antibiotics = self.patient.medications.find(PneumoniaValueSet).after(arrow.now().shift(days=-30))
        if len(antibiotics) == 0:
            result.add_recommendation(PrescribeRecommendation(
                key='antibiotics',
                prescription=PneumoniaValueSet,
                title='Prescribe Antibiotics',
                narrative='Prescribe antibiotics based on culture results and guidelines.',
                patient=self.patient
            ))

        if self.in_numerator():
            result.status = STATUS_SATISFIED
            result.add_narrative('Pneumonia diagnosis confirmed and treatment initiated.')

        return result