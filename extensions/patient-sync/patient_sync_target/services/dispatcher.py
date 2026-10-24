"""Per-entity dispatcher: turns bundle records into SDK effects.

For the *currently possible* release, this handles Note, all clinical
Commands, and Task — the three entity types verified end-to-end against the
home-app handlers (see SPEC.md > ID preservation strategy).

Patient, PatientExternalIdentifier, and the rest are routed to
``unsupported_entities`` in the sync response until their plumbing fixes
land (SPEC.md > Plumbing fixes).
"""

from __future__ import annotations

from typing import Any

import arrow

from canvas_sdk.commands import (
    AdjustPrescriptionCommand,
    AllergyCommand,
    AssessCommand,
    ChartSectionReviewCommand,
    CloseGoalCommand,
    DiagnoseCommand,
    FamilyHistoryCommand,
    FollowUpCommand,
    GoalCommand,
    HistoryOfPresentIllnessCommand,
    ImagingOrderCommand,
    ImagingReviewCommand,
    InstructCommand,
    LabOrderCommand,
    LabReviewCommand,
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
    ReferralReviewCommand,
    RefillCommand,
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

# ImmunizationStatementCommand and ChangeMedicationCommand aren't re-exported
# from canvas_sdk.commands in the runtime allowlist — import them directly.
from canvas_sdk.commands.commands.change_medication import ChangeMedicationCommand
from canvas_sdk.commands.commands.immunization_statement import ImmunizationStatementCommand
from canvas_sdk.effects import Effect
from canvas_sdk.effects.note.note import Note as NoteEffect
from canvas_sdk.effects.patient.base import Patient as PatientEffect
from canvas_sdk.effects.patient.base import (
    PatientExternalIdentifier as PatientExternalIdentifierField,
)
from canvas_sdk.effects.task.task import AddTask
from canvas_sdk.v1.data import PracticeLocation, Staff
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.common import PersonSex
from canvas_sdk.v1.data.note import Note
from canvas_sdk.v1.data.task import Task


# schema_key → Command class. Every Command in the SDK maps here. Keys
# come from each class's ``Meta.key``.
SCHEMA_KEY_TO_COMMAND: dict[str, type] = {
    "adjustPrescription": AdjustPrescriptionCommand,
    "allergy": AllergyCommand,
    "assess": AssessCommand,
    "changeMedication": ChangeMedicationCommand,
    "chartSectionReview": ChartSectionReviewCommand,
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
    "pocLabTest": POCLabTestCommand,
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
    "updateDiagnosis": UpdateDiagnosisCommand,
    "updateGoal": UpdateGoalCommand,
    "vitals": VitalsCommand,
}

# Entity types this dispatcher knows how to write end-to-end. Anything not
# in this set is reported in the sync response's ``unsupported_entities``
# until its plumbing fix or new-effect work lands.
SUPPORTED_ENTITY_TYPES: frozenset[str] = frozenset({"Patient", "Note", "Command", "Task"})


class UnsupportedEntityType(Exception):
    """Raised when the bundle contains an entity type this release can't write."""


class UnknownCommandSchemaKey(Exception):
    """Raised when a Command record's schema_key has no SDK class mapping."""


class AlreadyApplied(Exception):
    """Raised when a record's id is already present on target — idempotent skip."""


def dispatch(entity_type: str, record: dict[str, Any]) -> Effect:
    """Build the create-with-preserved-id effect for one bundle record."""
    if entity_type == "Patient":
        return _dispatch_patient(record)
    if entity_type == "Note":
        return _dispatch_note(record)
    if entity_type == "Command":
        return _dispatch_command(record)
    if entity_type == "Task":
        return _dispatch_task(record)
    raise UnsupportedEntityType(entity_type)


def _dispatch_patient(record: dict[str, Any]) -> Effect:
    """Create a Patient with the anonymized fields from the bundle.

    **Patient keys are globally unique across Canvas instances by design.**
    The Patient effect rejects client-supplied `patient_id` on create
    (`canvas_sdk/effects/patient/base.py:176-183`), the server-side handler
    server-assigns a fresh key, and that's *intentional*: a given patient
    key only ever points to one instance. The new patient on target gets a
    different key from the source — that mismatch is surfaced back to the
    sync caller (see SPEC.md > API contract on the callback shape) so
    they can record the source-id → target-id mapping on their side.

    Cascade: every Note/Command/Task in the same bundle references the
    *source* patient_id, which won't match the target's new patient. Those
    records fail dispatch with patient-not-found and land in the response's
    ``errors``. Re-syncing or re-keying on the caller side is the path
    forward; in-bundle remap would require a "wait for effect settled"
    primitive the platform doesn't have yet (SPEC.md > SDK gaps).
    """
    external_identifiers = [
        PatientExternalIdentifierField(system=eid.get("system"), value=eid["value"])
        for eid in (record.get("external_identifiers") or [])
        if eid.get("value")
    ]
    return PatientEffect(
        first_name=record.get("first_name") or "Unknown",
        last_name=record.get("last_name") or "Unknown",
        middle_name=record.get("middle_name") or "",
        birthdate=_parse_date(record.get("birth_date")),
        sex_at_birth=_parse_sex(record.get("sex_at_birth")),
        social_security_number=record.get("social_security_number") or "",
        external_identifiers=external_identifiers or None,
    ).create()


def _parse_sex(value: str | None) -> PersonSex | None:
    if not value:
        return None
    try:
        return PersonSex(value)
    except ValueError:
        return None


def _dispatch_note(record: dict[str, Any]) -> Effect:
    """Create a Note with preserved id via the existing NoteEffect.

    The home-app handler (``home-app/plugin_io/interpreters/notes/base.py:43,201``)
    reads ``instance_id`` from the payload and assigns it to the note's
    ``externally_exposable_id`` on create. Verified end-to-end.

    Idempotent: if a Note already exists at this id, raise AlreadyApplied
    so the importer can count it as a skip rather than an error.

    GAP — Staff and PracticeLocation have no create-effect today (see SPEC.md
    > SDK gaps). NoteEffect's validator requires both to already exist on the
    target, so until the new-effect tier ships we fall back to *any* Staff /
    PracticeLocation present on target. If source's ids happen to match a
    target row (operator pre-provisioned, or coincidence), we honor them.
    an integrating system joins on Note / Command / Patient ids — Staff and
    Location ids aren't part of that contract — so the mismatch on those
    two specifically is acceptable for now.
    """
    if Note.objects.filter(id=record["id"]).exists():
        raise AlreadyApplied(f"Note {record['id']}")
    return NoteEffect(
        instance_id=record["id"],
        note_type_id=record["note_type_id"],
        datetime_of_service=_parse_datetime(record["datetime_of_service"]),
        patient_id=record["patient_id"],
        practice_location_id=_resolve_practice_location_id(record.get("location_id")),
        provider_id=_resolve_provider_id(record.get("provider_id")),
        title=record.get("title") or "",
    ).create()


def _resolve_provider_id(source_id: str | None) -> str | None:
    """Use source's provider_id if a matching Staff exists on target; else fall back to any."""
    if source_id and Staff.objects.filter(id=source_id).exists():
        return source_id
    fallback = Staff.objects.filter(active=True).values_list("id", flat=True).first()
    if fallback is None:
        fallback = Staff.objects.values_list("id", flat=True).first()
    return fallback


def _resolve_practice_location_id(source_id: str | None) -> str | None:
    """Use source's location_id if a matching PracticeLocation exists on target; else any."""
    if source_id and PracticeLocation.objects.filter(id=source_id).exists():
        return source_id
    fallback = PracticeLocation.objects.filter(active=True).values_list("id", flat=True).first()
    if fallback is None:
        fallback = PracticeLocation.objects.values_list("id", flat=True).first()
    return str(fallback) if fallback is not None else None


def _dispatch_command(record: dict[str, Any]) -> Effect:
    """Originate a Command with preserved command_uuid.

    Per the [Commands docs](https://docs.canvasmedical.com/sdk/commands/) —
    "Chaining Methods with a User-set UUID" — setting ``command_uuid``
    before ``.originate()`` causes the platform to use that UUID as the
    command's id. Verified server-side at
    ``home-app/plugin_io/interpreters/commands/originate.py:25-32``.

    The bundle's ``state`` for a row is always ``"committed"`` (the source
    walker filters to committed commands), so we originate-and-commit.
    """
    if Command.objects.filter(id=record["id"]).exists():
        raise AlreadyApplied(f"Command {record['id']}")
    schema_key = record["schema_key"]
    command_cls = SCHEMA_KEY_TO_COMMAND.get(schema_key)
    if command_cls is None:
        raise UnknownCommandSchemaKey(schema_key)

    # The SDK's pydantic command classes accept only the fields they model.
    # `record["data"]` is the raw payload from the source side, which may
    # contain extra/unmodeled fields — pass through only what the class
    # declares to avoid validation errors.
    data = record.get("data") or {}
    field_names = set(command_cls.model_fields.keys())
    kwargs = {k: v for k, v in data.items() if k in field_names}

    cmd = command_cls(
        note_uuid=record["note_id"],
        command_uuid=record["id"],
        **kwargs,
    )
    return cmd.originate(commit=True)


def _dispatch_task(record: dict[str, Any]) -> Effect:
    """Create a Task with preserved id via the AddTask effect.

    The home-app handler (``home-app/plugin_io/interpreters/tasks/add_task.py:31-32``)
    explicitly: ``data["integration_payload"]["externally_exposable_id"] = task_id``.
    """
    if Task.objects.filter(id=record["id"]).exists():
        raise AlreadyApplied(f"Task {record['id']}")
    kwargs: dict[str, Any] = {
        "id": record["id"],
        "patient_id": record.get("patient_id"),
        "title": record.get("title") or "",
    }
    if assignee := record.get("assignee_id"):
        kwargs["assignee_id"] = assignee
    if team := record.get("team_id"):
        kwargs["team_id"] = team
    if priority := record.get("priority"):
        kwargs["priority"] = priority
    if status := record.get("status"):
        kwargs["status"] = status
    if due := record.get("due"):
        kwargs["due"] = _parse_datetime(due)
    return AddTask(**kwargs).apply()


def _parse_datetime(value: str | None) -> Any:
    if not value:
        return None
    return arrow.get(value).datetime


def _parse_date(value: str | None) -> Any:
    if not value:
        return None
    return arrow.get(value).date()
