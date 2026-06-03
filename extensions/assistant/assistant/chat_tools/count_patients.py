"""`count_patients` chat tool: count patients matching filters."""

from typing import Any, ClassVar, Literal  # noqa: UP035

from pydantic import BaseModel, ConfigDict

from assistant.chat_tools_lib import apply_filter_args
from canvas_sdk.v1.data.patient import Patient


class CountPatientsArgs(BaseModel):
    """Arguments for the `count_patients` chat tool."""

    model_config = ConfigDict(extra="forbid")

    first_name: str | None = None
    last_name: str | None = None
    active: bool | None = None
    sex_at_birth: Literal["F", "M", "O", "UNK"] | None = None

    LOOKUPS: ClassVar[dict[str, str]] = {
        "first_name": "first_name__iexact",
        "last_name": "last_name__iexact",
        "active": "active",
        "sex_at_birth": "sex_at_birth",
    }


def count_patients(instance: Any, args: CountPatientsArgs) -> dict:
    """Handler for the `count_patients` chat tool."""
    qs = apply_filter_args(Patient.objects.all(), args, CountPatientsArgs.LOOKUPS)
    return {"count": qs.count()}

TOOL_SPEC = {
    "name": "count_patients",
    "description": "Count patients matching the given filters.",
    "args_model": CountPatientsArgs,
    "handler": count_patients,
    "mutates": False,
}
