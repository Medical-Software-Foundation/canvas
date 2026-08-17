from django.db.models.query import QuerySet
from pydantic import ValidationError

from canvas_sdk.commands import(
    AllergyCommand,
    AssessCommand,
    CloseGoalCommand,
    DiagnoseCommand,
    FamilyHistoryCommand,
    FollowUpCommand,
    GoalCommand,
    HistoryOfPresentIllnessCommand,
    ImagingReviewCommand,
    InstructCommand,
    LabReviewCommand,
    MedicalHistoryCommand,
    MedicationStatementCommand,
    PastSurgicalHistoryCommand,
    PerformCommand,
    PhysicalExamCommand,
    PlanCommand,
    POCLabTestCommand,
    QuestionnaireCommand,
    ReferralReviewCommand,
    RemoveAllergyCommand,
    ResolveConditionCommand,
    ReviewOfSystemsCommand,
    StopMedicationCommand,
    StructuredAssessmentCommand,
    TaskCommand,
    UncategorizedDocumentReviewCommand,
    UpdateDiagnosisCommand,
    UpdateGoalCommand,
    VitalsCommand,
)
from canvas_sdk.commands.commands.change_medication import ChangeMedicationCommand
from canvas_sdk.commands.commands.immunization_statement import ImmunizationStatementCommand


from canvas_sdk.effects import Effect
from canvas_sdk.effects.action_button import ReloadNoteActionButtonsEffect
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.medication import Medication
from canvas_sdk.v1.data.note import CurrentNoteStateEvent, Note, NoteStates
from canvas_sdk.v1.data.questionnaire import Interview

from logger import log


class CommitButtonHandler(ActionButton):
    BUTTON_TITLE = "Commit All Commands"
    BUTTON_KEY = "COMMIT_ALL_COMMANDS"
    BUTTON_LOCATION = ActionButton.ButtonLocation.NOTE_FOOTER

    SCHEMA_KEYS_TO_COMMANDS = {
        AllergyCommand.Meta.key: AllergyCommand,
        AssessCommand.Meta.key: AssessCommand,
        ChangeMedicationCommand.Meta.key: ChangeMedicationCommand,
        CloseGoalCommand.Meta.key: CloseGoalCommand,
        DiagnoseCommand.Meta.key: DiagnoseCommand,
        FamilyHistoryCommand.Meta.key: FamilyHistoryCommand,
        FollowUpCommand.Meta.key: FollowUpCommand,
        GoalCommand.Meta.key: GoalCommand,
        HistoryOfPresentIllnessCommand.Meta.key: HistoryOfPresentIllnessCommand,
        ImagingReviewCommand.Meta.key: ImagingReviewCommand,
        ImmunizationStatementCommand.Meta.key: ImmunizationStatementCommand,
        InstructCommand.Meta.key: InstructCommand,
        LabReviewCommand.Meta.key: LabReviewCommand,
        MedicalHistoryCommand.Meta.key: MedicalHistoryCommand,
        MedicationStatementCommand.Meta.key: MedicationStatementCommand,
        PastSurgicalHistoryCommand.Meta.key: PastSurgicalHistoryCommand,
        PerformCommand.Meta.key: PerformCommand,
        PlanCommand.Meta.key: PlanCommand,
        PhysicalExamCommand.Meta.key: PhysicalExamCommand,
        POCLabTestCommand.Meta.key: POCLabTestCommand,
        QuestionnaireCommand.Meta.key: QuestionnaireCommand,
        ReferralReviewCommand.Meta.key: ReferralReviewCommand,
        RemoveAllergyCommand.Meta.key: RemoveAllergyCommand,
        ResolveConditionCommand.Meta.key: ResolveConditionCommand,
        ReviewOfSystemsCommand.Meta.key: ReviewOfSystemsCommand,
        StopMedicationCommand.Meta.key: StopMedicationCommand,
        StructuredAssessmentCommand.Meta.key: StructuredAssessmentCommand,
        TaskCommand.Meta.key: TaskCommand,
        UncategorizedDocumentReviewCommand.Meta.key: UncategorizedDocumentReviewCommand,
        UpdateDiagnosisCommand.Meta.key: UpdateDiagnosisCommand,
        UpdateGoalCommand.Meta.key: UpdateGoalCommand,
        VitalsCommand.Meta.key: VitalsCommand,
    }

    def staged_commands(self, note_id: int) -> QuerySet[Command]:
        """Staged commands on this note that this button knows how to commit."""
        return Command.objects.filter(
            note_id=note_id,
            state="staged",
            schema_key__in=self.SCHEMA_KEYS_TO_COMMANDS.keys(),
        )

    def visible(self) -> bool:
        note_id = self.context["note_id"]

        note_current_state = CurrentNoteStateEvent.objects.get(note__dbid=note_id)
        if note_current_state.state == NoteStates.LOCKED:
            return False

        # Nothing to commit means nothing to show. Scoped to the mapped schema
        # keys so a note holding only commands this button can't commit — an
        # unsent Prescribe, say — doesn't surface a button that would do nothing.
        return self.staged_commands(note_id).exists()

    def handle(self) -> list[Effect]:
        effects = []
        note_id = self.context.get("note_id")

        for command in Command.objects.filter(note_id=note_id, state="staged"):
            schema = command.schema_key
            command_id = str(command.id)
            extra_params = {}

            # Questionnaires require a questionnaire_id to be committed
            if schema == QuestionnaireCommand.Meta.key and command.anchor_object_type == "interview":
                interview_dbid = command.anchor_object_dbid
                interview = Interview.objects.get(dbid=interview_dbid)
                questionnaire_id = interview.questionnaires.first().id
                extra_params["questionnaire_id"] = str(questionnaire_id)

            if schema == ImmunizationStatementCommand.Meta.key:
                coding_list = command.data.get("statement", {}).get("extra", {}).get("coding", [])
                cpt_code = [c["code"] for c in coding_list if c["system"] == "http://www.ama-assn.org/go/cpt"]
                cvx_code = [c["code"] for c in coding_list if c["system"] == "http://hl7.org/fhir/sid/cvx"]
                if cpt_code:
                    cpt_code = cpt_code[0]
                else:
                    cpt_code = ""
                if cvx_code:
                    cvx_code = cvx_code[0]
                else:
                    cvx_code = ""
                extra_params["cpt_code"] = cpt_code
                extra_params["cvx_code"] = cvx_code

            if schema == ChangeMedicationCommand.Meta.key:
                medication_dbid = command.data.get("medication", {}).get("value")
                if medication_dbid:
                    medication = Medication.objects.get(dbid=medication_dbid)
                    extra_params["medication_id"] = str(medication.id)

            command_class = self.SCHEMA_KEYS_TO_COMMANDS.get(schema)
            if command_class:
                try:
                    command_obj = command_class(command_uuid=command_id, **extra_params)
                    effects.append(command_obj.commit())
                    log.info(
                        f"Added commit effect for {schema} command id {command_id}"
                    )
                except ValidationError as e:
                    log.error(
                        f"Unable to add commit effect for {schema} command id {command_id} due to the following error:"
                    )
                    log.error(str(e))
            else:
                log.warning(
                    f"{schema.title()} command not able to be committed due to missing mapping."
                )

        # Committing removes these commands from the staged set, which changes
        # whether this button should be visible at all. Ask the note to
        # re-evaluate its buttons so it disappears once nothing is left to
        # commit, instead of lingering until the next page load. Appended last
        # because effects apply in order and the reload has to see the commits.
        if effects:
            note = Note.objects.get(dbid=note_id)
            effects.append(ReloadNoteActionButtonsEffect(id=note.id).apply())

        return effects
