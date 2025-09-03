import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientEventRecordSet
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED
from canvas_workflow_kit.recommendation import DiagnoseRecommendation, AdministrativeRecommendation, InstructionRecommendation, DataManagementRecommendation
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.value_set.v2022 import OfficeVisit, BehavioralHealthFollowUpVisit, EncounterToDocumentMedications
from canvas_workflow_kit.value_set.v2020 import BmiEncounterCodeSet
class OptOutValueSet(ValueSet):
    pass
class ClinicalProtocol(ClinicalQualityMeasure):
    def in_initial_population(self) -> bool:
        return True
    def in_denominator(self) -> bool:
        start_date = arrow.now().shift(months=-12)
        end_date = arrow.now()
        appointments = self.patient.reason_for_visits.find(OfficeVisit).before(end_date).after(start_date)
        return len(appointments) > 0
    def in_numerator(self) -> bool:
        opt_out = self.patient.conditions.find(OptOutValueSet)
        deceased = self.patient.conditions.find(ValueSet).before(arrow.now())
        canceled_appointments = self.patient.reason_for_visits.find(OfficeVisit).before(arrow.now()).after(arrow.now().shift(months=-12))
        no_show_appointments = self.patient.reason_for_visits.find(OfficeVisit).before(arrow.now()).after(arrow.now().shift(months=-12))
        return len(opt_out) == 0 and len(deceased) == 0 and len(canceled_appointments) == 0 and len(no_show_appointments) == 0
    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if not (self.in_initial_population() and self.in_denominator()):
            result.status = STATUS_SATISFIED
        else:
            result.status = STATUS_DUE
            if not self.in_numerator():
                diagnose_recommendation = DiagnoseRecommendation(
                    key='diagnose',
                    condition=OptOutValueSet,
                    title='Diagnose Opt-Out',
                    narrative='Diagnose the patient’s opt-out status.',
                    patient=self.patient
                )
                administrative_recommendation = AdministrativeRecommendation(
                    key='administrative',
                    title='Generate Appointment Report',
                    narrative='Generate a comprehensive report of all appointments.',
                    patient=self.patient
                )
                instruction_recommendation = InstructionRecommendation(
                    key='instruction',
                    title='Document Follow-Up Actions',
                    narrative='Ensure follow-up actions from past appointments are documented.',
                    patient=self.patient
                )
                data_management_recommendation = DataManagementRecommendation(
                    key='data_management',
                    title='Update EHR System',
                    narrative='Update the EHR system to reflect changes in appointment status.',
                    patient=self.patient
                )
                result.add_recommendation(diagnose_recommendation)
                result.add_recommendation(administrative_recommendation)
                result.add_recommendation(instruction_recommendation)
                result.add_recommendation(data_management_recommendation)
        return result