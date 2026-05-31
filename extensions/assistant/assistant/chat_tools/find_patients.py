"""`find_patients` chat tool: search the patient panel by name/MRN/attributes."""

from typing import (  # noqa: UP035 — sandbox only allows ClassVar via typing
    Any,
    ClassVar,
    Literal,
)

from pydantic import BaseModel, ConfigDict, Field

from assistant.chat_tools_lib import (
    DEFAULT_RESULT_LIMIT,
    MAX_RESULT_LIMIT,
    apply_filter_args,
)
from canvas_sdk.v1.data.patient import Patient


class FindPatientsArgs(BaseModel):
    """Arguments for the `find_patients` chat tool."""

    model_config = ConfigDict(extra="forbid")

    first_name: str | None = Field(None, description="Case-insensitive exact match.")
    last_name: str | None = Field(None, description="Case-insensitive exact match.")
    mrn: str | None = Field(None, description="Medical record number, exact match.")
    active: bool | None = None
    sex_at_birth: Literal["F", "M", "O", "UNK"] | None = None
    limit: int = Field(
        DEFAULT_RESULT_LIMIT,
        ge=1,
        le=MAX_RESULT_LIMIT,
        description=f"Max results (default {DEFAULT_RESULT_LIMIT}, max {MAX_RESULT_LIMIT}).",
    )

    LOOKUPS: ClassVar[dict[str, str]] = {
        "first_name": "first_name__iexact",
        "last_name": "last_name__iexact",
        "mrn": "mrn",
        "active": "active",
        "sex_at_birth": "sex_at_birth",
    }


def find_patients(instance: Any, args: FindPatientsArgs) -> dict:
    """Handler for the `find_patients` chat tool."""
    qs = apply_filter_args(Patient.objects.all(), args, FindPatientsArgs.LOOKUPS)
    rows = list(
        qs.order_by("last_name", "first_name").values(
            "id", "first_name", "last_name", "birth_date", "sex_at_birth", "active", "mrn"
        )[: args.limit]
    )
    for r in rows:
        if r.get("birth_date"):
            r["birth_date"] = r["birth_date"].isoformat()
    return {"results": rows, "count": len(rows)}

TOOL_SPEC = {
    "name": "find_patients",
    "description": "Search for patients by name, MRN, or attributes. Returns matching patients "
    "with their core demographics.",
    "args_model": FindPatientsArgs,
    "handler": find_patients,
    "mutates": False,
}
