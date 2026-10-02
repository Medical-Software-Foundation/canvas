"""Query builder — turns a validated `Report` into a Django QuerySet.

Critically, this layer assumes the report has already been validated; it will
KeyError or attribute-error on bad input. Always run `validate_report` first.

Safety knobs:
- `MAX_ROWS` caps result-set size; if exceeded, the caller refuses to render.
"""

import uuid
from datetime import date, datetime
from typing import Any

from django.db.models import Avg, Count, Max, Min, Q, Sum
from django.db.models.query import QuerySet
from logger import log

from report_builder.reports.models import (
    AggregateColumn,
    AggregateCondition,
    FieldCondition,
    RelativeDate,
    Report,
)
from report_builder.schemas.base import EntitySchema
from report_builder.schemas.registry import ENTITY_REGISTRY

MAX_ROWS = 10_000
PRE_RUN_HOOKS: list[Any] = []

_DJANGO_LOOKUP = {
    "eq": "exact",
    "ne": "exact",
    "lt": "lt",
    "lte": "lte",
    "gt": "gt",
    "gte": "gte",
    "in": "in",
    "not_in": "in",
    "contains": "icontains",
    "starts_with": "istartswith",
    "is_null": "isnull",
}

_AGGREGATE_FNS = {
    "count": Count,
    "min": Min,
    "max": Max,
    "sum": Sum,
    "avg": Avg,
}



def _resolve_value(value: Any, as_of_date: date) -> Any:
    if isinstance(value, RelativeDate):
        return value.resolve(as_of_date)
    if isinstance(value, list):
        return [_resolve_value(v, as_of_date) for v in value]
    return value


def _q_for_field_condition(
    target_entity: EntitySchema, condition: FieldCondition, as_of_date: date
) -> Q:
    lookup = _DJANGO_LOOKUP[condition.op]
    value = _resolve_value(condition.value, as_of_date)
    key = f"{condition.field}__{lookup}" if lookup != "exact" else condition.field

    if condition.op == "is_null":
        return Q(**{f"{condition.field}__isnull": bool(value)})

    q = Q(**{key: value})
    if condition.op in ("ne", "not_in"):
        return ~q
    return q


def _apply_field_condition(
    qs: QuerySet, entity: EntitySchema, condition: FieldCondition, as_of_date: date
) -> QuerySet:
    q = _q_for_field_condition(entity, condition, as_of_date)
    return qs.filter(q)


def _build_subfilter_q(
    target_entity: EntitySchema,
    rel_path: str,
    sub_filters: tuple[FieldCondition, ...],
    as_of_date: date,
) -> Q:
    """Build a Q expression scoped to the related entity for use in `filter=`.

    All sub-filter keys are prefixed with `rel_path__` because the annotation is
    rooted on the *root* entity and reaches the target via the relationship.
    """
    q = Q()
    for sub in sub_filters:
        sub_q = _q_for_field_condition(target_entity, sub, as_of_date)
        prefixed = _prefix_q(sub_q, rel_path)
        q &= prefixed
    return q


def _prefix_q(q: Q, prefix: str) -> Q:
    """Prefix every leaf key in `q` with `prefix__` (for sub-filter scoping)."""
    new_children: list[Any] = []
    children: list[Any] = list(q.children)
    for child in children:
        if isinstance(child, Q):
            new_children.append(_prefix_q(child, prefix))
        else:
            key, value = child
            new_children.append((f"{prefix}__{key}", value))
    return Q(*new_children, _connector=q.connector, _negated=q.negated)


def _annotation_name() -> str:
    return f"_agg_{uuid.uuid4().hex[:8]}"


def _aggregate_target_path(rel_orm_path: str, target_entity: EntitySchema, aggregate_field: str | None) -> str:
    if aggregate_field is None:
        return rel_orm_path
    return f"{rel_orm_path}__{aggregate_field}"


def _apply_aggregate_filter(
    qs: QuerySet,
    entity: EntitySchema,
    condition: AggregateCondition,
    as_of_date: date,
) -> tuple[QuerySet, str]:
    rel = entity.relationship(condition.relationship)
    assert rel is not None  # guaranteed by validator
    target = ENTITY_REGISTRY[rel.target_entity]
    fn = _AGGREGATE_FNS[condition.fn]

    target_path = _aggregate_target_path(rel.orm_path, target, condition.aggregate_field)
    filter_q = _build_subfilter_q(target, rel.orm_path, condition.sub_filters, as_of_date)
    name = _annotation_name()

    annotation_kwargs: dict[str, Any] = {}
    if condition.sub_filters:
        annotation_kwargs[name] = fn(target_path, filter=filter_q)
    else:
        annotation_kwargs[name] = fn(target_path)

    qs = qs.annotate(**annotation_kwargs)

    compare_lookup = _DJANGO_LOOKUP[condition.compare_op]
    key = f"{name}__{compare_lookup}" if compare_lookup != "exact" else name
    filter_q_compare = Q(**{key: condition.compare_value})
    if condition.compare_op == "ne":
        filter_q_compare = ~filter_q_compare

    qs = qs.filter(filter_q_compare)
    return qs, name


def _apply_aggregate_column(
    qs: QuerySet, entity: EntitySchema, col: AggregateColumn, as_of_date: date
) -> tuple[QuerySet, str]:
    rel = entity.relationship(col.relationship)
    assert rel is not None
    target = ENTITY_REGISTRY[rel.target_entity]
    fn = _AGGREGATE_FNS[col.fn]

    target_path = _aggregate_target_path(rel.orm_path, target, col.aggregate_field)
    filter_q = _build_subfilter_q(target, rel.orm_path, col.sub_filters, as_of_date)
    name = _annotation_name()

    annotation_kwargs: dict[str, Any] = {}
    if col.sub_filters:
        annotation_kwargs[name] = fn(target_path, filter=filter_q)
    else:
        annotation_kwargs[name] = fn(target_path)

    return qs.annotate(**annotation_kwargs), name


def build_queryset(report: Report, as_of_date: date) -> tuple[QuerySet, list[tuple[str, str]]]:
    """Build a queryset for `report` with `as_of_date` applied to relative dates.

    Returns `(queryset, annotation_columns)`. `annotation_columns` is a list of
    `(label, annotation_name)` tuples — one entry per AggregateColumn, in the
    order they were declared.
    """
    entity = ENTITY_REGISTRY[report.root_entity]
    qs = entity.model.objects.all()

    for hook in PRE_RUN_HOOKS:
        qs = hook(qs, report, as_of_date) or qs

    for cond in report.conditions:
        if isinstance(cond, FieldCondition):
            qs = _apply_field_condition(qs, entity, cond, as_of_date)
        else:
            qs, _ = _apply_aggregate_filter(qs, entity, cond, as_of_date)

    annotation_columns: list[tuple[str, str]] = []
    for col in report.aggregate_columns:
        qs, name = _apply_aggregate_column(qs, entity, col, as_of_date)
        annotation_columns.append((col.label, name))

    return qs.order_by("dbid"), annotation_columns


def serialize_row(
    row: Any, entity: EntitySchema, columns: tuple[str, ...], annotation_columns: list[tuple[str, str]]
) -> dict[str, Any]:
    """Convert a queryset row to a JSON-safe dict.

    Lookups go through `getattr` so this works for both real model instances and
    test doubles. `dbid` and the externally-exposable `id` are always included.
    """
    out: dict[str, Any] = {
        "id": str(getattr(row, "id", "")),
        "dbid": getattr(row, "dbid", None),
    }
    for col in columns:
        out[col] = _coerce_for_json(getattr(row, col, None))
    for label, name in annotation_columns:
        out[label] = _coerce_for_json(getattr(row, name, None))
    return out


def _coerce_for_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, str)):
        return value
    return str(value)


def page_queryset(qs: QuerySet, page: int, per_page: int) -> tuple[list[Any], int, bool]:
    """Slice `qs` to (page, per_page). Returns (rows, total, too_large)."""
    total = qs.count()
    if total > MAX_ROWS:
        return [], total, True

    per_page = max(1, min(per_page, 100))
    page = max(1, page)
    start = (page - 1) * per_page
    end = start + per_page
    rows = list(qs[start:end])
    return rows, total, False


def safe_run(report: Report, as_of_date: date, page: int, per_page: int) -> dict[str, Any]:
    """Build, page, and serialize results for `report`."""
    entity = ENTITY_REGISTRY[report.root_entity]
    qs, annotation_columns = build_queryset(report, as_of_date)
    rows, total, too_large = page_queryset(qs, page, per_page)

    if too_large:
        log.info(f"report-builder: result too large for report '{report.name}' ({total} rows)")
        return {
            "rows": [],
            "total": total,
            "page": page,
            "per_page": per_page,
            "too_large": True,
            "max_rows": MAX_ROWS,
        }

    return {
        "rows": [
            serialize_row(row, entity, report.columns, annotation_columns) for row in rows
        ],
        "total": total,
        "page": page,
        "per_page": min(max(per_page, 1), 100),
        "too_large": False,
        "max_rows": MAX_ROWS,
        "annotation_columns": [label for label, _ in annotation_columns],
    }
