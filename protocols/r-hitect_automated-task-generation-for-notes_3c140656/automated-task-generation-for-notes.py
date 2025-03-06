import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientEventRecordSet
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED
from canvas_workflow_kit.recommendation import TaskRecommendation, InstructionRecommendation
from canvas_workflow_kit.value_set import ValueSet
class NoteStatusValueSet(ValueSet): pass
class CareNavigatorProtocol(ClinicalQualityMeasure):
    def in_initial_population(self) -> bool:
        return True
    def in_denominator(self) -> bool:
        notes = self.patient.interviews.find(NoteStatusValueSet)
        return len(notes) > 0
    def in_numerator(self) -> bool:
        notes = self.patient.interviews.find(NoteStatusValueSet)
        open_notes = notes.filter(status='open')
        closed_notes = notes.filter(status='closed')
        return len(open_notes) == 0 and len(closed_notes) > 0
    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        result.status = STATUS_DUE
        result.add_recommendation(TaskRecommendation(
            key='note_closure',
            title='Close Open Notes',
            narrative='Close the open notes with the required coding.',
            patient=self.patient
        ))
        result.add_recommendation(InstructionRecommendation(
            key='update_status',
            title='Update Note Status',
            narrative='Update the status of the notes to reflect ongoing patient care activities.',
            patient=self.patient
        ))
        return result