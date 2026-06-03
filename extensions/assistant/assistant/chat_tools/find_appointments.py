"""`find_appointments` chat tool: search scheduled appointments."""

from datetime import date
from typing import Any, ClassVar, Literal  # noqa: UP035

from pydantic import BaseModel, ConfigDict, Field

from assistant.chat_tools_lib import MAX_RESULT_LIMIT, apply_filter_args
from canvas_sdk.v1.data.appointment import Appointment

_APPT_STATUS = Literal[
    "unconfirmed",
    "attempted",
    "confirmed",
    "arrived",
    "roomed",
    "exited",
    "noshowed",
    "cancelled",
]


class FindAppointmentsArgs(BaseModel):
    """Arguments for the `find_appointments` chat tool."""

    model_config = ConfigDict(extra="forbid")

    patient_id: str | None = None
    provider_id: str | None = Field(None, description="Staff id of the provider.")
    date_from: date | None = Field(None, description="ISO date YYYY-MM-DD.")
    date_to: date | None = Field(None, description="ISO date YYYY-MM-DD.")
    status_in: list[_APPT_STATUS] | None = None
    limit: int = Field(
        20,
        ge=1,
        le=MAX_RESULT_LIMIT,
        description=f"Max results (default 20, max {MAX_RESULT_LIMIT}).",
    )

    LOOKUPS: ClassVar[dict[str, str]] = {
        "patient_id": "patient__id",
        "provider_id": "provider__id",
        "date_from": "start_time__date__gte",
        "date_to": "start_time__date__lte",
        "status_in": "status__in",
    }


def find_appointments(instance: Any, args: FindAppointmentsArgs) -> dict:
    """Handler for the `find_appointments` chat tool."""
    qs = apply_filter_args(Appointment.objects.all(), args, FindAppointmentsArgs.LOOKUPS)
    rows = list(
        qs.order_by("start_time").values(
            "id",
            "start_time",
            "duration_minutes",
            "status",
            "patient__id",
            "patient__first_name",
            "patient__last_name",
            "provider__id",
            "provider__first_name",
            "provider__last_name",
        )[: args.limit]
    )
    results = []
    for r in rows:
        results.append(
            {
                "id": r["id"],
                "start_time": r["start_time"].isoformat() if r["start_time"] else None,
                "duration_minutes": r["duration_minutes"],
                "status": r["status"],
                "patient_id": r["patient__id"],
                "patient_name": " ".join(
                    filter(None, [r["patient__first_name"], r["patient__last_name"]])
                ).strip()
                or None,
                "provider_id": r["provider__id"],
                "provider_name": " ".join(
                    filter(None, [r["provider__first_name"], r["provider__last_name"]])
                ).strip()
                or None,
            }
        )
    return {"results": results, "count": len(results)}

TOOL_SPEC = {
    "name": "find_appointments",
    "description": "Search for appointments. Sorted by start_time ascending. Filter by patient, "
    "provider (staff_id), date range, and/or status.",
    "args_model": FindAppointmentsArgs,
    "handler": find_appointments,
    "mutates": False,
}
