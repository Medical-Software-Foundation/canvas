"""Prefill a template command from the same command type in a prior note.

Each mapper reads the stored ``Command.data`` shape (the same shapes the
carry-forward reference plugin reads) and sets fields on a fresh SDK command.
Only command types with a mapper here can be carried forward; the builder UI
offers the toggle for these alone.
"""

from typing import Any, Callable

from canvas_sdk.commands import (
    AssessCommand,
    FollowUpCommand,
    HistoryOfPresentIllnessCommand,
    InstructCommand,
    LabOrderCommand,
    PerformCommand,
    PlanCommand,
    ReasonForVisitCommand,
    TaskCommand,
)
from canvas_sdk.commands.base import _BaseCommand
from canvas_sdk.commands.commands.task import AssigneeType, TaskAssigner
from canvas_sdk.commands.constants import CodeSystems, Coding
from canvas_sdk.v1.data.reason_for_visit import ReasonForVisitSettingCoding
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.condition import Condition
from canvas_sdk.v1.data.note import Note, NoteType
from canvas_sdk.v1.data.staff import Staff

from charting_tools.icd10 import condition_id_of

Mapper = Callable[[Any, dict[str, Any]], None]


def _reason_for_visit(cmd: ReasonForVisitCommand, data: dict[str, Any]) -> None:
    if coding := data.get("coding"):
        setting = (
            ReasonForVisitSettingCoding.objects.filter(code=coding.get("value"))
            .order_by("dbid")
            .last()
        )
        if setting:
            cmd.structured = True
            cmd.coding = str(setting.id)
    cmd.comment = data.get("comment") or ""


def _narrative(cmd: HistoryOfPresentIllnessCommand | PlanCommand, data: dict[str, Any]) -> None:
    cmd.narrative = data.get("narrative") or ""


def _instruct(cmd: InstructCommand, data: dict[str, Any]) -> None:
    if instruct := data.get("instruct"):
        codings = (instruct.get("extra") or {}).get("coding") or []
        if codings:
            coding = codings[0]
            if coding.get("system") == CodeSystems.SNOMED:
                cmd.coding = Coding(
                    system=coding["system"],
                    code=str(coding["code"]),
                    display=coding.get("display") or "",
                )
            elif coding.get("system") == CodeSystems.UNSTRUCTURED:
                cmd.coding = Coding(system=coding["system"], code=coding.get("display") or "")
    cmd.comment = data.get("narrative") or ""


def _perform(cmd: PerformCommand, data: dict[str, Any]) -> None:
    if perform := data.get("perform"):
        cmd.cpt_code = perform.get("value")
    cmd.notes = data.get("notes") or ""


def _assess(cmd: AssessCommand, data: dict[str, Any]) -> None:
    status_map = {
        "improved": AssessCommand.Status.IMPROVED,
        "stable": AssessCommand.Status.STABLE,
        "deteriorated": AssessCommand.Status.DETERIORATED,
    }
    # The earlier Assess's condition, when it holds a condition id. One that
    # diagnosed a new condition holds an ICD-10 code instead, which an Assess
    # can't take, so its condition isn't carried forward.
    condition_dbid = condition_id_of((data.get("condition") or {}).get("value"))
    if condition_dbid is not None:
        condition = Condition.objects.filter(dbid=condition_dbid, entered_in_error__isnull=True).first()
        if condition:
            cmd.condition_id = str(condition.id)
    cmd.background = data.get("background") or ""
    cmd.status = status_map.get(data.get("status") or "")
    cmd.narrative = data.get("narrative") or ""


def _follow_up(cmd: FollowUpCommand, data: dict[str, Any]) -> None:
    coding = data.get("coding")
    setting = (
        ReasonForVisitSettingCoding.objects.filter(code=coding.get("value")).order_by("dbid").last()
        if coding
        else None
    )
    if setting:
        cmd.structured = True
        cmd.reason_for_visit = str(setting.id)
    else:
        cmd.structured = False
        cmd.reason_for_visit = data.get("reason_for_visit")
    if note_type_ref := data.get("note_type"):
        note_type = NoteType.objects.filter(dbid=note_type_ref.get("value")).first()
        cmd.note_type_id = str(note_type.id) if note_type else None
    # The requested date is left blank: last visit's date is in the past.
    cmd.comment = data.get("comment") or ""


def _task(cmd: TaskCommand, data: dict[str, Any]) -> None:
    assignee_map = {
        "assignee": AssigneeType.STAFF,
        "team": AssigneeType.TEAM,
        "unassigned": AssigneeType.UNASSIGNED,
        "role": AssigneeType.ROLE,
    }
    cmd.title = data.get("title") or ""
    if assign_to := data.get("assign_to"):
        kind, _, ident = str(assign_to.get("value") or "").partition("-")
        if kind in assignee_map:
            cmd.assign_to = TaskAssigner(
                to=assignee_map[kind], id=int(ident) if ident.isdigit() else None
            )
    cmd.comment = data.get("comment") or ""
    cmd.labels = [label["text"] for label in (data.get("labels") or []) if label.get("text")]


def _lab_order(cmd: LabOrderCommand, data: dict[str, Any]) -> None:
    if partner := data.get("lab_partner"):
        cmd.lab_partner = partner.get("value")
    cmd.tests_order_codes = [t["value"] for t in (data.get("tests") or []) if t.get("value")]
    if provider_ref := data.get("ordering_provider"):
        staff = Staff.objects.filter(dbid=provider_ref.get("value")).first()
        cmd.ordering_provider_key = str(staff.id) if staff else None
    cmd.diagnosis_codes = [d["value"] for d in (data.get("diagnosis") or []) if d.get("value")]
    cmd.fasting_required = data.get("fasting_status") is True
    cmd.comment = data.get("comment") or ""


MAPPERS: dict[str, Mapper] = {
    ReasonForVisitCommand.Meta.key: _reason_for_visit,
    HistoryOfPresentIllnessCommand.Meta.key: _narrative,
    PlanCommand.Meta.key: _narrative,
    InstructCommand.Meta.key: _instruct,
    PerformCommand.Meta.key: _perform,
    AssessCommand.Meta.key: _assess,
    FollowUpCommand.Meta.key: _follow_up,
    TaskCommand.Meta.key: _task,
    LabOrderCommand.Meta.key: _lab_order,
}


def supports_carry_forward(schema_key: str) -> bool:
    """Return whether a command type can be prefilled from a prior note."""
    return schema_key in MAPPERS


def find_previous_command(note: Note, schema_key: str) -> Command | None:
    """Return the most recent committed command of this type from an earlier note.

    "Earlier" means an older date of service for the same patient. Entered-in-error
    commands and uncommitted drafts are skipped.
    """
    return (
        Command.objects.filter(
            patient_id=note.patient_id,
            schema_key=schema_key,
            committer__isnull=False,
            entered_in_error__isnull=True,
            note__datetime_of_service__lt=note.datetime_of_service,
        )
        .exclude(note_id=note.dbid)
        .order_by("-note__datetime_of_service", "-dbid")
        .first()
    )


def apply_carry_forward(cmd: _BaseCommand, previous: Command) -> None:
    """Copy the prior command's values onto ``cmd`` in place."""
    MAPPERS[previous.schema_key](cmd, previous.data or {})


__all__ = ["apply_carry_forward", "find_previous_command", "supports_carry_forward"]
