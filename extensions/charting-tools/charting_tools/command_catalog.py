"""Commands an admin can add to a template, keyed by command schema key."""

from typing import Callable, NamedTuple

from canvas_sdk.commands import (
    AdjustPrescriptionCommand,
    AllergyCommand,
    AssessCommand,
    CloseGoalCommand,
    DiagnoseCommand,
    FamilyHistoryCommand,
    FollowUpCommand,
    GoalCommand,
    HistoryOfPresentIllnessCommand,
    ImagingOrderCommand,
    OrderDmeCommand,
    ImmunizationStatementCommand,
    ImmunizeCommand,
    InstructCommand,
    LabOrderCommand,
    MedicalHistoryCommand,
    MedicationStatementCommand,
    PastSurgicalHistoryCommand,
    PerformCommand,
    PhysicalExamCommand,
    PlanCommand,
    POCLabTestCommand,
    PrescribeCommand,
    QuestionnaireCommand,
    ReasonForVisitCommand,
    ReferCommand,
    RefillCommand,
    RemoveAllergyCommand,
    ResolveConditionCommand,
    ReviewOfSystemsCommand,
    StopMedicationCommand,
    StructuredAssessmentCommand,
    TaskCommand,
    UpdateDiagnosisCommand,
    UpdateGoalCommand,
    VitalsCommand,
)
from canvas_sdk.commands.base import _BaseCommand


class CatalogEntry(NamedTuple):
    """A command offered in the template builder."""

    label: str
    command_class: Callable[..., _BaseCommand]


# Every entry here originates as an empty command. Review commands and
# ChartSectionReview are left out because they need a document or section to exist.
CATALOG: dict[str, CatalogEntry] = {
    cls.Meta.key: CatalogEntry(label, cls)
    for label, cls in (
        ("Reason for visit", ReasonForVisitCommand),
        ("History of present illness", HistoryOfPresentIllnessCommand),
        ("Review of systems", ReviewOfSystemsCommand),
        ("Physical exam", PhysicalExamCommand),
        ("Questionnaire", QuestionnaireCommand),
        ("Structured assessment", StructuredAssessmentCommand),
        ("Vitals", VitalsCommand),
        ("Diagnose", DiagnoseCommand),
        ("Assess", AssessCommand),
        ("Update diagnosis", UpdateDiagnosisCommand),
        ("Resolve condition", ResolveConditionCommand),
        ("Plan", PlanCommand),
        ("Instruct", InstructCommand),
        ("Goal", GoalCommand),
        ("Update goal", UpdateGoalCommand),
        ("Close goal", CloseGoalCommand),
        ("Follow up", FollowUpCommand),
        ("Task", TaskCommand),
        ("Lab order", LabOrderCommand),
        ("Imaging order", ImagingOrderCommand),
        ("DME order", OrderDmeCommand),
        ("Refer", ReferCommand),
        ("Perform", PerformCommand),
        ("POC lab test", POCLabTestCommand),
        ("Prescribe", PrescribeCommand),
        ("Refill", RefillCommand),
        ("Adjust prescription", AdjustPrescriptionCommand),
        ("Stop medication", StopMedicationCommand),
        ("Medication statement", MedicationStatementCommand),
        ("Allergy", AllergyCommand),
        ("Remove allergy", RemoveAllergyCommand),
        ("Past medical history", MedicalHistoryCommand),
        ("Past surgical history", PastSurgicalHistoryCommand),
        ("Family history", FamilyHistoryCommand),
        ("Immunize", ImmunizeCommand),
        ("Immunization statement", ImmunizationStatementCommand),
    )
}
