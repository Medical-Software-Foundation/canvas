import re
from typing import Any

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
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.medication import Medication
from canvas_sdk.v1.data.note import CurrentNoteStateEvent, Note, NoteStates, NoteTypeCategories
from canvas_sdk.v1.data.questionnaire import Interview

from logger import log

# Note states Canvas treats as locked, and as deleted or canceled.
LOCKED_STATES = (NoteStates.LOCKED, NoteStates.RELOCKED, NoteStates.SIGNED)
DELETED_STATES = (NoteStates.DELETED, NoteStates.CANCELLED)

# Fields each command needs filled in before Canvas commits it, matching the command
# schemas in canvas-core. Questionnaire, Change Medication and Immunization Statement
# have no entry and are not checked.
REQUIRED_FIELDS = {
    AllergyCommand.Meta.key: ("allergy",),
    AssessCommand.Meta.key: ("condition",),
    CloseGoalCommand.Meta.key: ("goal_id",),
    DiagnoseCommand.Meta.key: ("diagnose",),
    FamilyHistoryCommand.Meta.key: ("family_history",),
    FollowUpCommand.Meta.key: ("requested_date", "note_type"),
    GoalCommand.Meta.key: ("goal_statement", "start_date"),
    HistoryOfPresentIllnessCommand.Meta.key: ("narrative",),
    InstructCommand.Meta.key: ("instruct",),
    LabReviewCommand.Meta.key: ("report",),
    MedicalHistoryCommand.Meta.key: ("past_medical_history",),
    MedicationStatementCommand.Meta.key: ("medication",),
    PastSurgicalHistoryCommand.Meta.key: ("past_surgical_history",),
    PerformCommand.Meta.key: ("perform",),
    PlanCommand.Meta.key: ("narrative",),
    POCLabTestCommand.Meta.key: ("template",),
    RemoveAllergyCommand.Meta.key: ("allergy",),
    ResolveConditionCommand.Meta.key: ("condition",),
    StopMedicationCommand.Meta.key: ("medication",),
    TaskCommand.Meta.key: ("title", "assign_to"),
    UpdateDiagnosisCommand.Meta.key: ("condition", "new_condition"),
    UpdateGoalCommand.Meta.key: ("goal_statement",),
}

# Field labels set explicitly in the canvas-core command schemas. Any other field
# uses Django's default label, built from the field name.
FIELD_LABELS = {
    (FollowUpCommand.Meta.key, "note_type"): "Visit Type",
    (POCLabTestCommand.Meta.key, "template"): "POC Lab Test",
    (UpdateDiagnosisCommand.Meta.key, "new_condition"): "New Diagnosis",
}

NOT_IN_NOTE = "Saved to this note but not shown in it"


def missing_fields_reason(field_labels: list[str]) -> str:
    """The skip reason naming the empty required fields, such as "Empty required field: Narrative"."""
    noun = "field" if len(field_labels) == 1 else "fields"
    return f"Empty required {noun}: {', '.join(field_labels)}"


def field_label(schema_key: str, field: str) -> str:
    """The label Canvas shows for a command field, such as "Narrative" or "Visit Type"."""
    return FIELD_LABELS.get((schema_key, field), field.replace("_", " ").capitalize())


def is_blank(value: Any) -> bool:
    """Whether Canvas treats a command field value as empty."""
    if isinstance(value, str):
        return not value.strip()
    return value is None or value == [] or value == {}


def normalize_uuid(value: Any) -> str:
    """A UUID as lowercase hex without dashes, so both stored forms compare equal."""
    return str(value).replace("-", "").lower()


def command_label(command_class: Any) -> str:
    """A readable command name, such as "History Of Present Illness" or "POC Lab Test"."""
    name = command_class.__name__.removesuffix("Command")
    return re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", name)


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

    def visible(self) -> bool:
        note = Note.objects.select_related("note_type_version").get(dbid=self.context["note_id"])
        return self.accepts_commits(note)

    @staticmethod
    def accepts_commits(note: Note) -> bool:
        """Whether Canvas allows commands on the note to be committed.

        Deleted and canceled notes reject commits. Locked, relocked and signed notes
        reject them too, except data notes.
        """
        current_state = CurrentNoteStateEvent.objects.filter(note__dbid=note.dbid).first()
        if current_state is None:
            return True
        if current_state.state in DELETED_STATES:
            return False
        if current_state.state in LOCKED_STATES:
            return note.note_type_version.category == NoteTypeCategories.DATA
        return True

    @staticmethod
    def command_uuids_in_body(note: Note) -> set[str]:
        """The normalized UUIDs of the commands shown in the note body."""
        return {
            normalize_uuid(command_uuid)
            for line in note.body or []
            if line.get("type") == "command"
            and (command_uuid := (line.get("data") or {}).get("command_uuid"))
        }

    def handle(self) -> list[Effect]:
        effects = []
        skipped = []
        note_id = self.context.get("note_id")
        note = Note.objects.select_related("note_type_version").get(dbid=note_id)

        if not self.accepts_commits(note):
            log.info(f"Note {note_id} does not accept commits; no commands committed")
            return []

        uuids_in_body = self.command_uuids_in_body(note)

        for command in Command.objects.filter(note_id=note_id, state="staged"):
            schema = command.schema_key
            command_id = str(command.id)
            extra_params = {}

            command_class = self.SCHEMA_KEYS_TO_COMMANDS.get(schema)
            if not command_class:
                log.warning(
                    f"{schema.title()} command not able to be committed due to missing mapping."
                )
                continue

            if normalize_uuid(command_id) not in uuids_in_body:
                log.warning(f"Skipped {schema} command id {command_id}: not in the note body")
                skipped.append({"label": command_label(command_class), "reason": NOT_IN_NOTE})
                continue

            missing_fields = [
                field
                for field in REQUIRED_FIELDS.get(schema, ())
                if is_blank((command.data or {}).get(field))
            ]
            if missing_fields:
                log.info(
                    f"Skipped {schema} command id {command_id}: empty required fields "
                    f"{', '.join(missing_fields)}"
                )
                skipped.append(
                    {
                        "label": command_label(command_class),
                        "reason": missing_fields_reason(
                            [field_label(schema, field) for field in missing_fields]
                        ),
                    }
                )
                continue

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

        if skipped:
            effects.append(
                LaunchModalEffect(
                    content=render_to_string("templates/skipped_commands.html", {"skipped": skipped}),
                    title="Some commands were not committed",
                ).apply()
            )
        return effects
