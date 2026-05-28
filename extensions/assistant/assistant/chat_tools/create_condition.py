"""`create_condition` chat tool (mutation): add a diagnosis via Diagnose command."""

import uuid
from datetime import date as _date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from canvas_sdk.commands import DiagnoseCommand
from canvas_sdk.effects import Effect
from canvas_sdk.v1.data.note import Note
from canvas_sdk.v1.data.patient import Patient


class CreateConditionArgs(BaseModel):
    """Arguments for the `create_condition` chat tool."""

    model_config = ConfigDict(extra="forbid")

    patient_id: str = Field(..., description="Required.")
    icd10_code: str = Field(
        ...,
        description="ICD-10 code, e.g. 'E11.9'. Required. Case-insensitive.",
    )
    note_id: str | None = Field(
        None,
        description=(
            "Target note for the Diagnose command. Defaults to the "
            "patient's most recent note when omitted."
        ),
    )
    background: str | None = Field(
        None,
        description="Optional clinical background/context for the diagnosis.",
    )
    today_assessment: str | None = Field(
        None,
        description="Optional today's assessment narrative.",
    )
    approximate_date_of_onset: _date | None = Field(
        None,
        description="Optional onset date, ISO YYYY-MM-DD.",
    )


def create_condition(
    instance: Any, args: CreateConditionArgs, staff_id: str | None
) -> tuple[dict, list[Effect]]:
    """Handler for the `create_condition` mutation."""
    # Normalize the ICD-10 code: strip whitespace, uppercase, remove internal
    # spaces. Done inline rather than via @field_validator because pydantic's
    # `field_validator` isn't on the sandbox import allowlist.
    icd10 = args.icd10_code.strip().upper().replace(" ", "")
    if not icd10:
        return {"error": "icd10_code is required"}, []

    try:
        patient = Patient.objects.get(id=args.patient_id)
    except Patient.DoesNotExist:
        return {"error": f"patient {args.patient_id!r} not found"}, []

    # Resolve target note: explicit arg wins, else patient's most recent.
    if args.note_id:
        note = (
            Note.objects.filter(id=args.note_id, patient__id=args.patient_id)
            .values("id", "title", "note_type", "datetime_of_service")
            .first()
        )
        if not note:
            return {
                "error": f"note {args.note_id!r} not found for patient {args.patient_id!r}",
            }, []
    else:
        note = (
            Note.objects.filter(patient__id=args.patient_id)
            .order_by("-datetime_of_service")
            .values("id", "title", "note_type", "datetime_of_service")
            .first()
        )
        if not note:
            return {
                "error": (
                    f"no notes found for patient {args.patient_id!r}; "
                    "create an encounter first or provide note_id explicitly"
                ),
            }, []

    command_uuid = str(uuid.uuid4())
    cmd = DiagnoseCommand(
        note_uuid=str(note["id"]),
        icd10_code=icd10,
        background=args.background or None,
        today_assessment=args.today_assessment or None,
        approximate_date_of_onset=args.approximate_date_of_onset,
    )
    # Pre-set the command_uuid so we can chain originate → commit in one turn.
    cmd.command_uuid = command_uuid
    effects = [cmd.originate(), cmd.commit()]

    patient_name = f"{patient.first_name} {patient.last_name}".strip()
    return (
        {
            "queued": True,
            "patient_id": args.patient_id,
            "patient_name": patient_name or None,
            "icd10_code": icd10,
            "note_id": note["id"],
            "note_title": note["title"] or None,
            "note_datetime_of_service": (
                note["datetime_of_service"].isoformat()
                if note["datetime_of_service"]
                else None
            ),
            "background": args.background or None,
            "today_assessment": args.today_assessment or None,
            "approximate_date_of_onset": (
                args.approximate_date_of_onset.isoformat()
                if args.approximate_date_of_onset
                else None
            ),
            "command_uuid": command_uuid,
            "note": (
                "Diagnose command queued on the target note. The diagnosis "
                "appears on the problem list only after the clinician signs "
                "that note."
            ),
        },
        effects,
    )

TOOL_SPEC = {
    "name": "create_condition",
    "description": "Add a diagnosis to a patient's chart via a Diagnose command on a "
    "note. Mutating tool — the user must approve before it actually "
    "runs. Requires an ICD-10 code (e.g. 'E11.9', 'I10'). If "
    "`note_id` is omitted, defaults to the patient's most recent "
    "note. The diagnosis won't appear on the problem list until the "
    "clinician signs that note — make that expectation clear in your "
    "answer. Don't guess ICD-10 codes; ask the user or use "
    "`web_search` to confirm one if needed.",
    "args_model": CreateConditionArgs,
    "handler": create_condition,
    "mutates": True,
}
