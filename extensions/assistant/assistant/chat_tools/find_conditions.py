"""`find_conditions` chat tool: list a patient's diagnosed conditions."""

from typing import Any, ClassVar  # noqa: UP035

from pydantic import BaseModel, ConfigDict, Field

from assistant.chat_tools_lib import (
    DEFAULT_RESULT_LIMIT,
    MAX_RESULT_LIMIT,
    apply_filter_args,
)
from canvas_sdk.v1.data.condition import Condition


class FindConditionsArgs(BaseModel):
    """Arguments for the `find_conditions` chat tool."""

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


def find_conditions(instance: Any, args: FindConditionsArgs) -> dict:
    """Handler for the `find_conditions` chat tool."""
    qs = apply_filter_args(
        Condition.objects.filter(deleted=False),
        args,
        FindConditionsArgs.LOOKUPS,
    )
    qs = qs.prefetch_related("codings").order_by("-onset_date")[: args.limit]
    results = []
    for cond in qs:
        names: list[str] = []
        seen: set[str] = set()
        for c in cond.codings.all():
            name = (c.display or "").strip()
            if name and name not in seen:
                seen.add(name)
                names.append(name)
        results.append(
            {
                "id": cond.id,
                "name": names[0] if names else None,
                "name_aliases": names[1:] or None,
                "clinical_status": cond.clinical_status,
                "onset_date": cond.onset_date.isoformat() if cond.onset_date else None,
                "resolution_date": cond.resolution_date.isoformat()
                if cond.resolution_date
                else None,
                "notes": cond.notes or None,
                "surgical": cond.surgical,
            }
        )
    return {"results": results, "count": len(results), "patient_id": args.patient_id}

TOOL_SPEC = {
    "name": "find_conditions",
    "description": "Get a patient's diagnosed conditions. Requires patient_id.",
    "args_model": FindConditionsArgs,
    "handler": find_conditions,
    "mutates": False,
}
