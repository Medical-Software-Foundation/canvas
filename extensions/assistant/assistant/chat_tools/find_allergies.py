"""`find_allergies` chat tool: list a patient's allergies and intolerances."""

from typing import Any, ClassVar  # noqa: UP035 — sandbox only allows ClassVar via typing

from pydantic import BaseModel, ConfigDict, Field

from assistant.chat_tools_lib import (
    DEFAULT_RESULT_LIMIT,
    MAX_RESULT_LIMIT,
    apply_filter_args,
)
from canvas_sdk.v1.data.allergy_intolerance import AllergyIntolerance


class FindAllergiesArgs(BaseModel):
    """Arguments for the `find_allergies` chat tool."""

    model_config = ConfigDict(extra="forbid")

    patient_id: str = Field(..., description="Patient id (required).")
    limit: int = Field(
        DEFAULT_RESULT_LIMIT,
        ge=1,
        le=MAX_RESULT_LIMIT,
        description=f"Max results (default {DEFAULT_RESULT_LIMIT}, max {MAX_RESULT_LIMIT}).",
    )

    LOOKUPS: ClassVar[dict[str, str]] = {
        "patient_id": "patient__id",
    }


def find_allergies(instance: Any, args: FindAllergiesArgs) -> dict:
    """Handler for the `find_allergies` chat tool."""
    qs = apply_filter_args(
        AllergyIntolerance.objects.filter(deleted=False),
        args,
        FindAllergiesArgs.LOOKUPS,
    )
    rows = list(
        qs.order_by("-recorded_date").values(
            "id", "narrative", "severity", "status", "onset_date"
        )[: args.limit]
    )
    for r in rows:
        if r.get("onset_date"):
            r["onset_date"] = r["onset_date"].isoformat()
    return {"results": rows, "count": len(rows), "patient_id": args.patient_id}

TOOL_SPEC = {
    "name": "find_allergies",
    "description": "Get a patient's allergies and intolerances. Requires patient_id.",
    "args_model": FindAllergiesArgs,
    "handler": find_allergies,
    "mutates": False,
}
