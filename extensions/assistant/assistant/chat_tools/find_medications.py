"""`find_medications` chat tool: list a patient's medication statements."""

from typing import Any, ClassVar  # noqa: UP035

from pydantic import BaseModel, ConfigDict, Field

from assistant.chat_tools_lib import (
    DEFAULT_RESULT_LIMIT,
    MAX_RESULT_LIMIT,
    apply_filter_args,
)
from canvas_sdk.v1.data.medication_statement import MedicationStatement


class FindMedicationsArgs(BaseModel):
    """Arguments for the `find_medications` chat tool."""

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


def find_medications(instance: Any, args: FindMedicationsArgs) -> dict:
    """Handler for the `find_medications` chat tool."""
    qs = apply_filter_args(
        MedicationStatement.objects.all(),
        args,
        FindMedicationsArgs.LOOKUPS,
    )
    qs = (
        qs.select_related("medication")
        .prefetch_related("medication__codings")
        .order_by("-start_date")[: args.limit]
    )
    results = []
    for ms in qs:
        names: list[str] = []
        medication_status = None
        if ms.medication is not None:
            medication_status = ms.medication.status
            seen: set[str] = set()
            for c in ms.medication.codings.all():
                name = (c.display or "").strip()
                if name and name not in seen:
                    seen.add(name)
                    names.append(name)
        results.append(
            {
                "id": ms.id,
                "medication_name": names[0] if names else None,
                "medication_aliases": names[1:] or None,
                "status": medication_status,
                "start_date": ms.start_date.isoformat() if ms.start_date else None,
                "end_date": ms.end_date.isoformat() if ms.end_date else None,
                "dose_quantity": ms.dose_quantity,
                "dose_form": ms.dose_form or None,
                "dose_route": ms.dose_route or None,
                "dose_frequency": ms.dose_frequency,
                "dose_frequency_interval": ms.dose_frequency_interval or None,
                "sig": ms.sig_original_input or None,
            }
        )
    return {"results": results, "count": len(results), "patient_id": args.patient_id}

TOOL_SPEC = {
    "name": "find_medications",
    "description": "Get a patient's medication statements. Requires patient_id.",
    "args_model": FindMedicationsArgs,
    "handler": find_medications,
    "mutates": False,
}
