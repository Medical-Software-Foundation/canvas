import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientEventRecordSet
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.recommendation import PerformRecommendation, InstructionRecommendation

class SpravatoValueSet(ValueSet):
    pass

class MonitoringFormValueSet(ValueSet):
    pass

class JanssenReportValueSet(ValueSet):
    pass

class SpravatoProtocol(ClinicalQualityMeasure):
    def in_initial_population(self) -> bool:
        spravato_procedures = self.patient.procedures.find(SpravatoValueSet)
        return len(spravato_procedures) > 0

    def in_denominator(self) -> bool:
        return self.in_initial_population()

    def in_numerator(self) -> bool:
        monitoring_forms = self.patient.procedures.find(MonitoringFormValueSet)
        janssen_reports = self.patient.procedures.find(JanssenReportValueSet)
        return len(monitoring_forms) > 0 and len(janssen_reports) > 0

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if self.in_denominator():
            if self.in_numerator():
                result.status = STATUS_SATISFIED
                result.add_narrative('Spravato treatment and reporting completed.')
            else:
                result.status = STATUS_DUE
                result.add_narrative('Complete patient monitoring form and report to Janssen.')
                perform_recommendation = PerformRecommendation(
                    key='monitoring_form',
                    procedure=MonitoringFormValueSet,
                    title='Complete Monitoring Form',
                    narrative='Collect data for required patient monitoring form.',
                    patient=self.patient
                )
                instruction_recommendation = InstructionRecommendation(
                    key='janssen_report',
                    instruction=JanssenReportValueSet,
                    title='Report to Janssen',
                    narrative='Report variables back to Janssen.',
                    patient=self.patient
                )
                result.add_recommendation(perform_recommendation)
                result.add_recommendation(instruction_recommendation)
        return result