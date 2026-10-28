"""The commands and text fields dot phrases work in.

Each entry was confirmed on a test instance: a plugin edit to the field shows on screen without a
reload. Lab order, Point-of-care lab test, and Remove past medical history were added later from
the SDK command classes and Canvas's own field limits. Questionnaire-style commands (Questionnaire, ROS, Physical Exam, Structured Assessment)
are left out because a plugin edit to their text answers is accepted but never saved.
ChangeMedicationCommand is not an allowed plugin import, and Clipboard, Private Note, Visual Exam
Finding, and Snooze Protocol have no SDK edit.
"""

from __future__ import annotations

from typing import Any, NamedTuple

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
    ImagingReviewCommand,
    ImmunizationStatementCommand,
    InstructCommand,
    LabOrderCommand,
    LabReviewCommand,
    MedicalHistoryCommand,
    MedicationStatementCommand,
    PastSurgicalHistoryCommand,
    PerformCommand,
    PlanCommand,
    POCLabTestCommand,
    PrescribeCommand,
    ReasonForVisitCommand,
    ReferCommand,
    ReferralReviewCommand,
    RefillCommand,
    RemoveAllergyCommand,
    RemovePastMedicalHistoryCommand,
    ResolveConditionCommand,
    StopMedicationCommand,
    TaskCommand,
    UncategorizedDocumentReviewCommand,
    UpdateDiagnosisCommand,
    UpdateGoalCommand,
    VitalsCommand,
)


class CommandSpec(NamedTuple):
    """One command type: where its events come from and which text fields phrases can fill."""

    key: str  # stable key stored in a phrase's "use in" list
    label: str  # what admins and providers see
    event_prefix: str  # e.g. "PLAN" for PLAN_COMMAND__POST_UPDATE
    command_class: Any
    # (field name in the event, field name on the SDK command)
    fields: tuple[tuple[str, str], ...]
    # Review commands do not fire POST_VALIDATION, so nothing can block them.
    validates: bool = True


_REVIEW = (("message_to_patient", "message_to_patient"), ("internal_comment", "comment"))

NOTE_COMMANDS: tuple[CommandSpec, ...] = (
    CommandSpec("plan", "Plan", "PLAN", PlanCommand, (("narrative", "narrative"),)),
    CommandSpec("hpi", "History of present illness", "HISTORY_OF_PRESENT_ILLNESS", HistoryOfPresentIllnessCommand, (("narrative", "narrative"),)),
    # Instruct stores its comment as "narrative" in the event; the SDK field is "comment".
    CommandSpec("instruct", "Instruct", "INSTRUCT", InstructCommand, (("narrative", "comment"),)),
    CommandSpec("perform", "Perform", "PERFORM", PerformCommand, (("notes", "notes"),)),
    CommandSpec("assess", "Assess", "ASSESS", AssessCommand, (("background", "background"), ("narrative", "narrative"))),
    CommandSpec("diagnose", "Diagnose", "DIAGNOSE", DiagnoseCommand, (("background", "background"), ("today_assessment", "today_assessment"))),
    CommandSpec("updatedx", "Update diagnosis", "UPDATE_DIAGNOSIS", UpdateDiagnosisCommand, (("background", "background"), ("narrative", "narrative"))),
    CommandSpec("allergy", "Allergy", "ALLERGY", AllergyCommand, (("narrative", "narrative"),)),
    CommandSpec("removeallergy", "Remove allergy", "REMOVE_ALLERGY", RemoveAllergyCommand, (("narrative", "narrative"),)),
    CommandSpec("resolve", "Resolve condition", "RESOLVE_CONDITION", ResolveConditionCommand, (("rationale", "rationale"),)),
    CommandSpec("stopmed", "Stop medication", "STOP_MEDICATION", StopMedicationCommand, (("rationale", "rationale"),)),
    CommandSpec("removepmh", "Remove past medical history", "REMOVE_PAST_MEDICAL_HISTORY", RemovePastMedicalHistoryCommand, (("rationale", "rationale"),)),
    CommandSpec("pmh", "Past medical history", "MEDICAL_HISTORY", MedicalHistoryCommand, (("comments", "comments"),)),
    CommandSpec("psh", "Surgical history", "SURGICAL_HISTORY", PastSurgicalHistoryCommand, (("comment", "comment"),)),
    CommandSpec("fhx", "Family history", "FAMILY_HISTORY", FamilyHistoryCommand, (("note", "note"),)),
    CommandSpec("immstmt", "Immunization statement", "IMMUNIZATION_STATEMENT", ImmunizationStatementCommand, (("comments", "comments"),)),
    CommandSpec("medstmt", "Medication statement", "MEDICATION_STATEMENT", MedicationStatementCommand, (("sig", "sig"),)),
    CommandSpec("goal", "Goal", "GOAL", GoalCommand, (("goal_statement", "goal_statement"), ("progress", "progress"))),
    CommandSpec("updategoal", "Update goal", "UPDATE_GOAL", UpdateGoalCommand, (("progress", "progress"),)),
    CommandSpec("closegoal", "Close goal", "CLOSE_GOAL", CloseGoalCommand, (("progress", "progress"),)),
    CommandSpec("rfv", "Reason for visit", "REASON_FOR_VISIT", ReasonForVisitCommand, (("comment", "comment"),)),
    CommandSpec("followup", "Follow-up", "FOLLOW_UP", FollowUpCommand, (("comment", "comment"),)),
    CommandSpec("task", "Task", "TASK", TaskCommand, (("title", "title"), ("comment", "comment"))),
    # Refer stores its internal comment as "internal_comment" in the event; the SDK field is "comment".
    CommandSpec("refer", "Refer", "REFER", ReferCommand, (("notes_to_specialist", "notes_to_specialist"), ("internal_comment", "comment"))),
    CommandSpec("imaging", "Imaging order", "IMAGING_ORDER", ImagingOrderCommand, (("additional_details", "additional_details"), ("comment", "comment"))),
    CommandSpec("vitals", "Vitals", "VITALS", VitalsCommand, (("note", "note"),)),
    # The lab order comment is sent to the lab with the order.
    CommandSpec("laborder", "Lab order", "LAB_ORDER", LabOrderCommand, (("comment", "comment"),)),
    CommandSpec("poclab", "Point-of-care lab test", "POC_LAB_TEST", POCLabTestCommand, (("remarks", "remarks"),)),
    CommandSpec("labreview", "Lab review", "LAB_REVIEW", LabReviewCommand, _REVIEW, validates=False),
    CommandSpec("imgreview", "Imaging review", "IMAGING_REVIEW", ImagingReviewCommand, _REVIEW, validates=False),
    CommandSpec("refreview", "Referral review", "REFERRAL_REVIEW", ReferralReviewCommand, _REVIEW, validates=False),
    CommandSpec("docreview", "Document review", "UNCATEGORIZED_DOCUMENT_REVIEW", UncategorizedDocumentReviewCommand, _REVIEW, validates=False),
)

# Prescription text goes to the pharmacy. Canvas rejects anything outside printable ASCII, and the
# Surescripts NewRx message caps the Sig at 1,000 characters and the note to pharmacist at 210.
RX_FIELDS: dict[str, tuple[str, int]] = {
    "sig": ("Sig", 1000),
    "note_to_pharmacist": ("Note to pharmacist", 210),
}

RX_COMMANDS: tuple[CommandSpec, ...] = (
    CommandSpec("prescribe", "Prescribe", "PRESCRIBE", PrescribeCommand, (("sig", "sig"), ("note_to_pharmacist", "note_to_pharmacist"))),
    CommandSpec("refill", "Refill", "REFILL", RefillCommand, (("sig", "sig"), ("note_to_pharmacist", "note_to_pharmacist"))),
    CommandSpec("adjustrx", "Adjust prescription", "ADJUST_PRESCRIPTION", AdjustPrescriptionCommand, (("sig", "sig"), ("note_to_pharmacist", "note_to_pharmacist"))),
)

ALL_COMMANDS: tuple[CommandSpec, ...] = NOTE_COMMANDS + RX_COMMANDS
RX_KEYS = frozenset(spec.key for spec in RX_COMMANDS)
NOTE_COMMAND_KEYS: tuple[str, ...] = tuple(spec.key for spec in NOTE_COMMANDS)
COMMAND_LABELS: dict[str, str] = {spec.key: spec.label for spec in NOTE_COMMANDS}
# A phrase with use_in None works in every note command except the review commands, which can't
# block recording when placeholders are left incomplete.
DEFAULT_USE_IN = frozenset(spec.key for spec in NOTE_COMMANDS if spec.validates)


def works_in(use_in: list[str] | None, command_key: str) -> bool:
    """Whether a phrase with this use_in is set up for this note command."""
    return command_key in DEFAULT_USE_IN if use_in is None else command_key in use_in

# The chart panel can add these as a new command in the note.
INSERTABLE: dict[str, Any] = {
    "plan": PlanCommand,
    "hpi": HistoryOfPresentIllnessCommand,
    "instruct": InstructCommand,
    "perform": PerformCommand,
}
INSERT_FIELD: dict[str, str] = {"plan": "narrative", "hpi": "narrative", "instruct": "comment", "perform": "notes"}

# Character limits on the text fields phrases expand into. Most come from the SDK command classes
# (canvas_sdk.commands, Field max_length); the review commands' 2,048 and Instruct's 4,000 come from
# the Canvas models those commands save to. A command with more than one text field uses the
# smallest of its limits. Lab order's 128 comes from the Canvas model too. Commands not listed
# have no limit.
FIELD_LIMITS: dict[str, int] = {
    "laborder": 128,
    "vitals": 150,
    "immstmt": 255,
    "allergy": 512,
    "removeallergy": 512,
    "fhx": 512,
    "removepmh": 512,
    "poclab": 512,
    "pmh": 1000,
    "psh": 1000,
    "medstmt": 1000,
    "stopmed": 1024,
    "resolve": 1024,
    "imaging": 1024,
    "assess": 2048,
    "diagnose": 2048,
    "labreview": 2048,
    "imgreview": 2048,
    "refreview": 2048,
    "docreview": 2048,
    "instruct": 4000,
}

# schema_key values Canvas uses for staged prescription commands in a note.
RX_SCHEMA_KEYS: dict[str, Any] = {
    "prescribe": PrescribeCommand,
    "refill": RefillCommand,
    "adjustPrescription": AdjustPrescriptionCommand,
}


def spec_for_event(event_name: str, suffix: str) -> CommandSpec | None:
    """Find the command for an event name like PLAN_COMMAND__POST_UPDATE."""
    for spec in ALL_COMMANDS:
        if event_name == f"{spec.event_prefix}_COMMAND__{suffix}":
            return spec
    return None
