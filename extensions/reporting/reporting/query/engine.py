"""Report execution: dataset + filters + measure + grouping + period comparison."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

from reporting.datasets import get_dataset
from reporting.query.filters import FilterClause, build_lookups
from reporting.query.measures import compute_value, count_specs
from reporting.query.periods import Period, PeriodSpec, compute_periods

# executor(model, lookups, group_paths, count_specs) -> list[row dict]
Executor = Callable[[Any, dict[str, Any], list[str], dict[str, Any]], list[dict[str, Any]]]


@dataclass(frozen=True)
class ReportQuery:
    dataset_key: str
    filters: list[FilterClause]
    measure_key: str
    group_by: str | None
    period: PeriodSpec | None = None


def _orm_executor(model, lookups, group_paths, specs):
    """Default executor: real Django ORM grouped Count query (runs in the sandbox)."""
    from django.db.models import Count, Q

    annotations = {}
    for name, spec in specs.items():
        if spec is None:
            annotations[name] = Count("dbid")
        else:
            annotations[name] = Count("dbid", filter=Q(**spec))
    qs = model.objects.filter(**lookups).values(*group_paths).annotate(**annotations)
    return list(qs)


def _group_label(dataset, dim, row) -> str:
    parts = [str(row.get(p, "")) for p in dim.display_paths]
    label = " ".join(p for p in parts if p).strip()
    return label or str(row.get(dim.group_path, ""))


def run_report(
    query: ReportQuery,
    anchor: date,
    executor: Executor | None = None,
) -> dict[str, Any]:
    executor = executor or _orm_executor
    dataset = get_dataset(query.dataset_key)
    measure = dataset.measures[query.measure_key]
    specs = count_specs(measure)
    # Base filters narrow the population for BOTH the numerator and denominator of
    # a measure; the measure's own num/den count specs further partition within it.
    base_lookups = build_lookups(query.filters)

    dim = dataset.dimensions[query.group_by] if query.group_by else None
    group_paths: list[str] = []
    if dim:
        group_paths = [dim.group_path, *dim.display_paths]

    spec = query.period or PeriodSpec(granularity="month", count=1, include_rolling_12=False)
    periods: list[Period] = compute_periods(spec, anchor)

    # group_key -> {"group_label": str, "values": {period_label: value}}
    merged: dict[Any, dict[str, Any]] = {}
    for period in periods:
        lookups = dict(base_lookups)
        lookups[f"{dataset.date_field}__gte"] = period.start
        lookups[f"{dataset.date_field}__lt"] = period.end
        rows = executor(dataset.model, lookups, group_paths, specs)
        for row in rows:
            key = row.get(dim.group_path) if dim else "__all__"
            entry = merged.setdefault(
                key,
                {"group_label": _group_label(dataset, dim, row) if dim else "All", "values": {}},
            )
            entry["values"][period.label] = compute_value(measure, row)

    return {
        "dataset": dataset.label,
        "measure": measure.label,
        "group_by": dim.label if dim else None,
        "periods": [p.label for p in periods],
        "rows": list(merged.values()),
    }
