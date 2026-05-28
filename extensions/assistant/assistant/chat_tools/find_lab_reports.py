"""`find_lab_reports` chat tool: list lab values from external lab reports."""

from datetime import date
from typing import Any, ClassVar  # noqa: UP035

from pydantic import BaseModel, ConfigDict, Field

from assistant.chat_tools_lib import MAX_RESULT_LIMIT, apply_filter_args
from canvas_sdk.v1.data.lab import LabValue


class FindLabReportsArgs(BaseModel):
    """Arguments for the `find_lab_reports` chat tool."""

    model_config = ConfigDict(extra="forbid")

    patient_id: str = Field(..., description="Patient id (required).")
    test_name_contains: str | None = Field(
        None,
        description=(
            "Case-insensitive substring match on the test name "
            "(e.g. 'A1c', 'LDL', 'Glucose')."
        ),
    )
    date_from: date | None = Field(None, description="ISO date YYYY-MM-DD.")
    date_to: date | None = Field(None, description="ISO date YYYY-MM-DD.")
    abnormal_only: bool = Field(
        False,
        description="When true, return only values flagged abnormal (H/L/HH/LL/etc.).",
    )
    limit: int = Field(
        20,
        ge=1,
        le=MAX_RESULT_LIMIT,
        description=f"Max results (default 20, max {MAX_RESULT_LIMIT}).",
    )

    LOOKUPS: ClassVar[dict[str, str]] = {
        "patient_id": "report__patient__id",
        "test_name_contains": "test__ontology_test_name__icontains",
        "date_from": "report__original_date__date__gte",
        "date_to": "report__original_date__date__lte",
    }


def find_lab_reports(instance: Any, args: FindLabReportsArgs) -> dict:
    """Handler for the `find_lab_reports` chat tool."""
    qs = apply_filter_args(
        LabValue.objects.filter(report__junked=False),
        args,
        FindLabReportsArgs.LOOKUPS,
    )
    # `abnormal_only` is a boolean toggle, not a value filter — handled outside
    # the lookup map.
    if args.abnormal_only:
        qs = qs.exclude(abnormal_flag="")
    rows = list(
        qs.order_by("-report__original_date").values(
            "id",
            "value",
            "units",
            "abnormal_flag",
            "reference_range",
            "low_threshold",
            "high_threshold",
            "observation_status",
            "test__ontology_test_name",
            "report__id",
            "report__original_date",
        )[: args.limit]
    )
    results = []
    for r in rows:
        results.append(
            {
                "id": r["id"],
                "test_name": r["test__ontology_test_name"] or None,
                "value": r["value"] or None,
                "units": r["units"] or None,
                "reference_range": r["reference_range"] or None,
                "low_threshold": r["low_threshold"] or None,
                "high_threshold": r["high_threshold"] or None,
                "abnormal_flag": r["abnormal_flag"] or None,
                "observation_status": r["observation_status"] or None,
                "date": (
                    r["report__original_date"].isoformat()
                    if r["report__original_date"]
                    else None
                ),
                "report_id": r["report__id"],
            }
        )
    return {"results": results, "count": len(results), "patient_id": args.patient_id}

TOOL_SPEC = {
    "name": "find_lab_reports",
    "description": "Get a patient's lab values from external lab reports. Returns one row "
    "per measurement (not per report) so a single test like A1C can be "
    "trended across visits. Use this for lab results (A1C, lipid panel, "
    "CBC, CMP, TSH, etc.) — distinct from `find_observations`, which "
    "covers in-clinic charted vitals. Filter by `test_name_contains` to "
    "narrow to one analyte. Requires patient_id.",
    "args_model": FindLabReportsArgs,
    "handler": find_lab_reports,
    "mutates": False,
}
