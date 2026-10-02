"""Measure definitions. All sums/ratios computed in Python (Sum/Avg are sandbox-blocked).

A measure declares one or more named COUNT specs. The engine turns each spec into a
Count("dbid", filter=Q(**lookup)) annotation (or Count("dbid") when the spec is None),
runs the grouped query, then calls compute_value() per row to derive the final number.
"""

from dataclasses import dataclass, field
from typing import Any, Optional

# A "count spec" is the ORM lookup kwargs for the Count filter, or None for count-all.
CountSpec = Optional[dict[str, Any]]


@dataclass(frozen=True)
class CountMeasure:
    key: str
    label: str
    where: dict[str, Any] | None = None  # None -> count everything

    kind: str = field(default="count", init=False)


@dataclass(frozen=True)
class RatioMeasure:
    key: str
    label: str
    numerator_where: dict[str, Any]
    denominator_where: dict[str, Any] | None = None  # None -> count-all denominator
    as_percent: bool = True

    kind: str = field(default="ratio", init=False)


Measure = CountMeasure | RatioMeasure


def count_specs(measure: Measure) -> dict[str, CountSpec]:
    """Return {annotation_name: count_spec} the engine must materialize."""
    if isinstance(measure, CountMeasure):
        return {f"{measure.key}__all": measure.where}
    return {
        f"{measure.key}__num": measure.numerator_where,
        f"{measure.key}__den": measure.denominator_where,
    }


def compute_value(measure: Measure, row: dict[str, Any]) -> float | int:
    """Derive the measure's value from a row of materialized named counts."""
    if isinstance(measure, CountMeasure):
        return row[f"{measure.key}__all"]
    num = row[f"{measure.key}__num"]
    den = row[f"{measure.key}__den"]
    if not den:
        return 0.0
    ratio = num / den
    return round(ratio * 100, 1) if measure.as_percent else round(ratio, 4)
