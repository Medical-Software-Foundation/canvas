"""`find_encounters` chat tool: search clinical encounters (visits)."""

from datetime import date
from typing import Any, ClassVar, Literal  # noqa: UP035

from pydantic import BaseModel, ConfigDict, Field

from assistant.chat_tools_lib import MAX_RESULT_LIMIT, apply_filter_args
from canvas_sdk.v1.data.encounter import Encounter

_ENC_STATE = Literal["STA", "PLA", "CON", "CAN"]
_ENC_MEDIUM = Literal["voice", "video", "office", "home", "offsite", "lab"]


class FindEncountersArgs(BaseModel):
    """Arguments for the `find_encounters` chat tool."""

    model_config = ConfigDict(extra="forbid")

    patient_id: str | None = None
    provider_id: str | None = Field(None, description="Staff id of the provider.")
    date_from: date | None = Field(None, description="ISO date YYYY-MM-DD.")
    date_to: date | None = Field(None, description="ISO date YYYY-MM-DD.")
    state_in: list[_ENC_STATE] | None = Field(
        None,
        description="Encounter states: STA=started, PLA=planned, CON=concluded, CAN=cancelled.",
    )
    medium_in: list[_ENC_MEDIUM] | None = None
    limit: int = Field(
        20,
        ge=1,
        le=MAX_RESULT_LIMIT,
        description=f"Max results (default 20, max {MAX_RESULT_LIMIT}).",
    )

    LOOKUPS: ClassVar[dict[str, str]] = {
        "patient_id": "note__patient__id",
        "provider_id": "note__provider__id",
        "date_from": "start_time__date__gte",
        "date_to": "start_time__date__lte",
        "state_in": "state__in",
        "medium_in": "medium__in",
    }


def find_encounters(instance: Any, args: FindEncountersArgs) -> dict:
    """Handler for the `find_encounters` chat tool."""
    qs = apply_filter_args(Encounter.objects.all(), args, FindEncountersArgs.LOOKUPS)
    rows = list(
        qs.order_by("-start_time").values(
            "id",
            "state",
            "medium",
            "start_time",
            "end_time",
            "note__id",
            "note__title",
            "note__note_type",
            "note__datetime_of_service",
            "note__patient__id",
            "note__patient__first_name",
            "note__patient__last_name",
            "note__provider__id",
            "note__provider__first_name",
            "note__provider__last_name",
        )[: args.limit]
    )
    results = []
    for r in rows:
        results.append(
            {
                "id": r["id"],
                "state": r["state"],
                "medium": r["medium"],
                "start_time": r["start_time"].isoformat() if r["start_time"] else None,
                "end_time": r["end_time"].isoformat() if r["end_time"] else None,
                "note_id": r["note__id"],
                "note_title": r["note__title"] or None,
                "note_type": r["note__note_type"] or None,
                "note_datetime_of_service": (
                    r["note__datetime_of_service"].isoformat()
                    if r["note__datetime_of_service"]
                    else None
                ),
                "patient_id": r["note__patient__id"],
                "patient_name": " ".join(
                    filter(
                        None,
                        [r["note__patient__first_name"], r["note__patient__last_name"]],
                    )
                ).strip()
                or None,
                "provider_id": r["note__provider__id"],
                "provider_name": " ".join(
                    filter(
                        None,
                        [r["note__provider__first_name"], r["note__provider__last_name"]],
                    )
                ).strip()
                or None,
            }
        )
    return {"results": results, "count": len(results)}

TOOL_SPEC = {
    "name": "find_encounters",
    "description": "Search for patient encounters (completed/in-progress visits). Distinct "
    "from `find_appointments` (scheduled future slots): an encounter is the "
    "clinical visit itself — office, telehealth, lab, etc. — and ties to a "
    "note where charting happened. Use this for 'what visits has she had', "
    "'when was her last office visit', or to find a note_id for a follow-up "
    "action. Sorted by start_time descending (most recent first).",
    "args_model": FindEncountersArgs,
    "handler": find_encounters,
    "mutates": False,
}
