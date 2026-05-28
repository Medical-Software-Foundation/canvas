"""`find_observations` chat tool: list a patient's clinical observations."""

from datetime import date
from typing import Any, ClassVar  # noqa: UP035

from pydantic import BaseModel, ConfigDict, Field

from assistant.chat_tools_lib import (
    DEFAULT_RESULT_LIMIT,
    MAX_RESULT_LIMIT,
    apply_filter_args,
)
from canvas_sdk.v1.data.observation import Observation


class FindObservationsArgs(BaseModel):
    """Arguments for the `find_observations` chat tool."""

    model_config = ConfigDict(extra="forbid")

    patient_id: str = Field(..., description="Patient id (required).")
    date_from: date | None = None
    date_to: date | None = None
    limit: int = Field(
        DEFAULT_RESULT_LIMIT,
        ge=1,
        le=MAX_RESULT_LIMIT,
        description=f"Max results (default {DEFAULT_RESULT_LIMIT}, max {MAX_RESULT_LIMIT}).",
    )

    LOOKUPS: ClassVar[dict[str, str]] = {
        "patient_id": "patient__id",
        "date_from": "effective_datetime__date__gte",
        "date_to": "effective_datetime__date__lte",
    }


def find_observations(instance: Any, args: FindObservationsArgs) -> dict:
    """Handler for the `find_observations` chat tool."""
    qs = apply_filter_args(
        Observation.objects.all(),
        args,
        FindObservationsArgs.LOOKUPS,
    )
    rows = list(
        qs.order_by("-effective_datetime").values(
            "id", "name", "value", "units", "category", "effective_datetime"
        )[: args.limit]
    )
    for r in rows:
        if r.get("effective_datetime"):
            r["effective_datetime"] = r["effective_datetime"].isoformat()
    return {"results": rows, "count": len(rows), "patient_id": args.patient_id}

TOOL_SPEC = {
    "name": "find_observations",
    "description": "Get a patient's clinical observations (vitals, lab values, etc). Requires patient_id.",
    "args_model": FindObservationsArgs,
    "handler": find_observations,
    "mutates": False,
}
