"""`find_staff` chat tool: search staff (providers, clinicians) by name."""

from typing import Any, ClassVar  # noqa: UP035 — sandbox only allows ClassVar via typing

from pydantic import BaseModel, ConfigDict, Field

from assistant.chat_tools_lib import (
    DEFAULT_RESULT_LIMIT,
    MAX_RESULT_LIMIT,
    apply_filter_args,
)
from canvas_sdk.v1.data.staff import Staff


class FindStaffArgs(BaseModel):
    """Arguments for the `find_staff` chat tool."""

    model_config = ConfigDict(extra="forbid")

    first_name: str | None = Field(None, description="Case-insensitive substring match.")
    last_name: str | None = Field(None, description="Case-insensitive substring match.")
    limit: int = Field(
        DEFAULT_RESULT_LIMIT,
        ge=1,
        le=MAX_RESULT_LIMIT,
        description=f"Max results (default {DEFAULT_RESULT_LIMIT}, max {MAX_RESULT_LIMIT}).",
    )

    # `__icontains` (not `__iexact`) — staff search is loose because users often
    # type partial names ("smith" should match "Smithson"). Different from
    # find_patients, which uses exact matching to avoid ambiguity at the chart.
    LOOKUPS: ClassVar[dict[str, str]] = {
        "first_name": "first_name__icontains",
        "last_name": "last_name__icontains",
    }


def find_staff(instance: Any, args: FindStaffArgs) -> dict:
    """Handler for the `find_staff` chat tool."""
    qs = apply_filter_args(Staff.objects.all(), args, FindStaffArgs.LOOKUPS)
    rows = list(
        qs.order_by("last_name", "first_name").values("id", "first_name", "last_name")[: args.limit]
    )
    return {"results": rows, "count": len(rows)}

TOOL_SPEC = {
    "name": "find_staff",
    "description": "Search for staff (providers, clinicians) by name.",
    "args_model": FindStaffArgs,
    "handler": find_staff,
    "mutates": False,
}
