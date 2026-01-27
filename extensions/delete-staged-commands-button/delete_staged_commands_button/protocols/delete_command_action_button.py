from canvas_sdk.effects import Effect
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.note import Note
from canvas_sdk.commands import *
from canvas_sdk.commands.commands.change_medication import ChangeMedicationCommand
from canvas_sdk.commands.commands.immunization_statement import ImmunizationStatementCommand

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
            AdjustPrescriptionCommand.Meta.key: AdjustPrescriptionCommand,
            AllergyCommand.Meta.key: AllergyCommand,
            AssessCommand.Meta.key: AssessCommand,
            ChangeMedicationCommand.Meta.key: ChangeMedicationCommand,
            CloseGoalCommand.Meta.key: CloseGoalCommand,
            DiagnoseCommand.Meta.key: DiagnoseCommand,
            PhysicalExamCommand.Meta.key: PhysicalExamCommand,
            FamilyHistoryCommand.Meta.key: FamilyHistoryCommand,
            FollowUpCommand.Meta.key: FollowUpCommand,
            GoalCommand.Meta.key: GoalCommand,
            HistoryOfPresentIllnessCommand.Meta.key: HistoryOfPresentIllnessCommand,
            ImagingOrderCommand.Meta.key: ImagingOrderCommand,
            ImagingReviewCommand.Meta.key: ImagingReviewCommand,
            ImmunizationStatementCommand.Meta.key: ImmunizationStatementCommand,
            InstructCommand.Meta.key: InstructCommand,
            LabOrderCommand.Meta.key: LabOrderCommand,
            LabReviewCommand.Meta.key: LabReviewCommand,
            MedicalHistoryCommand.Meta.key: MedicalHistoryCommand,
            MedicationStatementCommand.Meta.key: MedicationStatementCommand,
            PerformCommand.Meta.key: PerformCommand,
            PlanCommand.Meta.key: PlanCommand,
            PrescribeCommand.Meta.key: PrescribeCommand,
            QuestionnaireCommand.Meta.key: QuestionnaireCommand,
            ReasonForVisitCommand.Meta.key: ReasonForVisitCommand,
            ReferCommand.Meta.key: ReferCommand,
            ReferralReviewCommand.Meta.key: ReferralReviewCommand,
            RefillCommand.Meta.key: RefillCommand,
            RemoveAllergyCommand.Meta.key: RemoveAllergyCommand,
            ResolveConditionCommand.Meta.key: ResolveConditionCommand,
            ReviewOfSystemsCommand.Meta.key: ReviewOfSystemsCommand,
            StopMedicationCommand.Meta.key: StopMedicationCommand,
            StructuredAssessmentCommand.Meta.key: StructuredAssessmentCommand,
            PastSurgicalHistoryCommand.Meta.key: PastSurgicalHistoryCommand,
            TaskCommand.Meta.key: TaskCommand,
            UncategorizedDocumentReviewCommand.Meta.key: UncategorizedDocumentReviewCommand,
            UpdateDiagnosisCommand.Meta.key: UpdateDiagnosisCommand,
            UpdateGoalCommand.Meta.key: UpdateGoalCommand,
            VitalsCommand.Meta.key: VitalsCommand,
        }

        effects = []
        for command in commands_to_delete:
            if ModelClass := schema_map.get(command.schema_key):
                effects.append(ModelClass(command_uuid=str(command.id)).delete())
            else:
                log.warning(f"No model class found for command {command.schema_key}")

        return effects
