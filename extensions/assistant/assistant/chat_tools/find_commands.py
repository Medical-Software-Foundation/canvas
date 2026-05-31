"""`find_commands` chat tool: search structured charting commands on notes."""

from datetime import date
from typing import Any, ClassVar  # noqa: UP035

from pydantic import BaseModel, ConfigDict, Field

from assistant.chat_tools_lib import MAX_RESULT_LIMIT, apply_filter_args
from canvas_sdk.v1.data.command import Command


class FindCommandsArgs(BaseModel):
    """Arguments for the `find_commands` chat tool."""

    model_config = ConfigDict(extra="forbid")

    patient_id: str | None = None
    note_id: str | None = None
    schema_key_in: list[str] | None = Field(
        None,
        description=(
            "Filter by command type. Common values: 'diagnose', "
            "'prescribe', 'plan', 'assess', 'reason_for_visit', "
            "'physical_exam', 'lab_order', 'imaging_order', 'refer', "
            "'goal', 'instruct', 'questionnaire'."
        ),
    )
    committed_only: bool = Field(
        True,
        description="When true (default), only return commands with a committer set.",
    )
    include_entered_in_error: bool = Field(
        False,
        description="When false (default), exclude commands marked entered-in-error.",
    )
    date_from: date | None = Field(None, description="ISO date YYYY-MM-DD on created.")
    date_to: date | None = Field(None, description="ISO date YYYY-MM-DD on created.")
    limit: int = Field(
        20,
        ge=1,
        le=MAX_RESULT_LIMIT,
        description=f"Max results (default 20, max {MAX_RESULT_LIMIT}).",
    )

    # `committed_only` and `include_entered_in_error` aren't simple value
    # filters — they enable conditional queryset filters applied below.
    LOOKUPS: ClassVar[dict[str, str]] = {
        "patient_id": "patient__id",
        "note_id": "note__id",
        "schema_key_in": "schema_key__in",
        "date_from": "created__date__gte",
        "date_to": "created__date__lte",
    }


def find_commands(instance: Any, args: FindCommandsArgs) -> dict:
    """Handler for the `find_commands` chat tool."""
    qs = apply_filter_args(Command.objects.all(), args, FindCommandsArgs.LOOKUPS)
    if args.committed_only:
        qs = qs.filter(committer__isnull=False)
    if not args.include_entered_in_error:
        qs = qs.filter(entered_in_error__isnull=True)
    rows = list(
        qs.order_by("-created").values(
            "id",
            "schema_key",
            "state",
            "data",
            "anchor_object_type",
            "created",
            "modified",
            "patient__id",
            "note__id",
            "note__title",
            # CanvasUser uses `dbid` (no public UUID id), so the FK lookup
            # is committer__dbid / entered_in_error__dbid. Used only as a
            # not-null check below; we don't surface the dbid itself.
            "committer__dbid",
            "entered_in_error__dbid",
        )[: args.limit]
    )
    results = []
    for r in rows:
        results.append(
            {
                "id": r["id"],
                "schema_key": r["schema_key"] or None,
                "state": r["state"] or None,
                "committed": r["committer__dbid"] is not None,
                "entered_in_error": r["entered_in_error__dbid"] is not None,
                "data": r["data"],
                "anchor_object_type": r["anchor_object_type"] or None,
                "created": r["created"].isoformat() if r["created"] else None,
                "modified": r["modified"].isoformat() if r["modified"] else None,
                "patient_id": r["patient__id"],
                "note_id": r["note__id"],
                "note_title": r["note__title"] or None,
            }
        )
    return {"results": results, "count": len(results)}

TOOL_SPEC = {
    "name": "find_commands",
    "description": "Get clinical commands recorded on notes — the actual structured "
    "charting content (diagnoses, prescriptions, plans, assessments, "
    "reason-for-visit, etc.). Use this for 'what's on her current "
    "note', 'what did I prescribe last visit', 'show me today's "
    "diagnoses'. Defaults to committed (not draft) commands and "
    "excludes entered-in-error. Filter by patient_id, note_id, and/or "
    "`schema_key_in` (e.g. ['diagnose','prescribe']). The `data` "
    "field on each row carries the command's payload as JSON (icd10 "
    "code, sig text, narrative, etc.) — interpret per schema_key.",
    "args_model": FindCommandsArgs,
    "handler": find_commands,
    "mutates": False,
}
