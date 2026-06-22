"""Insurance coverage portal content (My Insurance tab).

Reads active, in-use coverages from the SDK Coverage model. Both filters matter:
``stack="IN_USE"`` excludes coverages the UI "Remove" action moved to REMOVED, and
``state="active"`` excludes inactive coverages. Coverage enums are not importable
in the Canvas sandbox, so the literal values are used directly.
"""

from datetime import date
from typing import Any

from canvas_sdk.v1.data.coverage import Coverage
from logger import log

STACK_IN_USE = "IN_USE"
STATE_ACTIVE = "active"
RANK_LABELS = {1: "Primary", 2: "Secondary", 3: "Tertiary"}


def list_coverages(patient_id: str) -> list[dict]:
    """Return the patient's active in-use coverages, primary rank first."""
    coverages = (
        Coverage.objects.filter(
            patient__id=patient_id,
            stack=STACK_IN_USE,
            state=STATE_ACTIVE,
        )
        .select_related("issuer")
        .order_by("coverage_rank")
    )

    result = []
    for cov in coverages:
        result.append(
            {
                "payer_name": cov.issuer.name if cov.issuer else None,
                "member_id": cov.id_number,
                "group_number": cov.group,
                "plan_type": _format_plan_type(cov.plan_type),
                "rank": RANK_LABELS.get(cov.coverage_rank),
                "start_date": _format_date(cov.coverage_start_date),
                "end_date": _format_date(cov.coverage_end_date),
            }
        )

    log.info(f"Found {len(result)} active coverages for patient {patient_id}")
    return result


def _format_plan_type(plan_type: Any) -> str | None:
    if not plan_type:
        return None
    return str(plan_type).replace("_", " ").title()


def _format_date(value: date | None) -> str | None:
    if not value:
        return None
    return value.strftime("%B %d, %Y")
