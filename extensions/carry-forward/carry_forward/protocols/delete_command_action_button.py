from canvas_sdk.effects import Effect
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.v1.data import Immunization
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.note import Note
from canvas_sdk.commands import *
from canvas_sdk.commands.commands.change_medication import ChangeMedicationCommand

from logger import log


class DeleteCommandActionButton(ActionButton):
    """
        Adds a Delete All Staged Commands action button to the note header

        When pressed it will delete all commands in the note that are in the "staged" state
    """


    BUTTON_TITLE = "Delete All Staged Commands"
    BUTTON_KEY = "DELETE_ALL_STAGED_COMMANDS"
    BUTTON_LOCATION = ActionButton.ButtonLocation.NOTE_HEADER

    def visible(self) -> bool:
        return True


    def handle(self) -> list[Effect]:
        """
            Function is kicked of when the button in the note is clicked. 

            It will insert empty commands of:
                Reason For Visit
                History of Present Illness
                Review of Systems
                Physical Exam
                Diagnose
                Plan
        """

        note_id = self.event.context['note_id']
        note = Note.objects.filter(dbid=note_id).first()
        commands_to_delete = Command.objects.filter(note=note, state="staged")


        schema_map = {
            "adjustPrescription": AdjustPrescriptionCommand,
            "allergy": AllergyCommand,
            "assess": AssessCommand,
            "changeMedication": ChangeMedicationCommand,
            "closeGoal": CloseGoalCommand,
            "diagnose": DiagnoseCommand,
            "exam": PhysicalExamCommand,
            "familyHistory": FamilyHistoryCommand,
            "followUp": FollowUpCommand,
            "goal": GoalCommand,
            "hpi": HistoryOfPresentIllnessCommand,
            "imagingOrder": ImagingOrderCommand,
            "imagingReview": ImagingReviewCommand,
            "immunizationStatement": ImmunizationStatementCommand,
            "instruct": InstructCommand,
            "labOrder": LabOrderCommand,
            "labReview": LabReviewCommand,
            "medicalHistory": MedicalHistoryCommand,
            "medicationStatement": MedicationStatementCommand,
            "perform": PerformCommand,
            "plan": PlanCommand,
            "prescribe": PrescribeCommand,
            "questionnaire": QuestionnaireCommand,
            "reasonForVisit": ReasonForVisitCommand,
            "refer": ReferCommand,
            "referralReview": ReferralReviewCommand,
            "refill": RefillCommand,
            "removeAllergy": RemoveAllergyCommand,
            "resolveCondition": ResolveConditionCommand,
            "ros": ReviewOfSystemsCommand,
            "stopMedication": StopMedicationCommand,
            "structuredAssessment": StructuredAssessmentCommand,
            "surgicalHistory": PastSurgicalHistoryCommand,
            "task": TaskCommand,
            "uncategorizedDocumentReview": UncategorizedDocumentReviewCommand,
            "updateDiagnosis": UpdateDiagnosisCommand,
            "updateGoal": UpdateGoalCommand,
            "vitals": VitalsCommand,
        }

        effects = []
        for command in commands_to_delete:
            if ModelClass := schema_map.get(command.schema_key):
                effects.append(ModelClass(command_uuid=str(command.id)).delete())
            else:
                log.warning(f"No model class found for command {command.schema_key}")

        return effects
