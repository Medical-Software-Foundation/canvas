"""`find_notes` chat tool: search a patient's clinical notes."""

from datetime import date
from typing import Any, ClassVar  # noqa: UP035

from pydantic import BaseModel, ConfigDict, Field

from assistant.chat_tools_lib import (
    DEFAULT_RESULT_LIMIT,
    MAX_RESULT_LIMIT,
    apply_filter_args,
)
from canvas_sdk.v1.data.note import Note


class FindNotesArgs(BaseModel):
    """Arguments for the `find_notes` chat tool."""

    model_config = ConfigDict(extra="forbid")

    patient_id: str = Field(..., description="Patient id (required).")
    date_from: date | None = Field(
        None, description="ISO date YYYY-MM-DD (inclusive, on datetime_of_service)."
    )
    date_to: date | None = Field(
        None, description="ISO date YYYY-MM-DD (inclusive, on datetime_of_service)."
    )
    provider_id: str | None = Field(None, description="Staff id of the note's provider.")
    limit: int = Field(
        DEFAULT_RESULT_LIMIT,
        ge=1,
        le=MAX_RESULT_LIMIT,
        description=f"Max results (default {DEFAULT_RESULT_LIMIT}, max {MAX_RESULT_LIMIT}).",
    )

    LOOKUPS: ClassVar[dict[str, str]] = {
        "patient_id": "patient__id",
        "date_from": "datetime_of_service__date__gte",
        "date_to": "datetime_of_service__date__lte",
        "provider_id": "provider__id",
    }


def find_notes(instance: Any, args: FindNotesArgs) -> dict:
    """Handler for the `find_notes` chat tool."""
    qs = apply_filter_args(Note.objects.all(), args, FindNotesArgs.LOOKUPS)
    rows = list(
        qs.order_by("-datetime_of_service").values(
            "id",
            "note_type",
            "title",
            "datetime_of_service",
            "place_of_service",
            "provider__id",
            "provider__first_name",
            "provider__last_name",
            "location__id",
            "location__full_name",
        )[: args.limit]
    )
    results = []
    for r in rows:
        results.append(
            {
                "id": r["id"],
                "note_type": r["note_type"] or None,
                "title": r["title"] or None,
                "datetime_of_service": (
                    r["datetime_of_service"].isoformat()
                    if r["datetime_of_service"]
                    else None
                ),
                "place_of_service": r["place_of_service"] or None,
                "provider_id": r["provider__id"],
                "provider_name": " ".join(
                    filter(None, [r["provider__first_name"], r["provider__last_name"]])
                ).strip()
                or None,
                "location_id": r["location__id"],
                "location_name": r["location__full_name"] or None,
            }
        )
    return {"results": results, "count": len(results), "patient_id": args.patient_id}

TOOL_SPEC = {
    "name": "find_notes",
    "description": "Get a patient's clinical notes. Sorted by datetime_of_service "
    "descending (most recent visit first). Filter by date range to "
    "pinpoint 'the note from 2/10' — the result includes "
    "datetime_of_service, note_type, provider, and location so you "
    "can confirm the match. Pair with `find_commands(note_id=...)` "
    "to read the structured content of a specific note. Requires "
    "patient_id.",
    "args_model": FindNotesArgs,
    "handler": find_notes,
    "mutates": False,
}
