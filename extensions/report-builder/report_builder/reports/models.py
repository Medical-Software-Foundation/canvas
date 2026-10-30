"""Report DTOs — the in-memory shape of a saved report.

Reports are also serialized to JSON (for storage and the API surface).
The wire format is a discriminated union via the `kind` field on conditions
and an explicit `_type` marker on `RelativeDate` values.
"""

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Literal, Union

ScalarOp = Literal[
    "eq", "ne", "lt", "lte", "gt", "gte",
    "in", "not_in", "contains", "starts_with", "is_null",
]
AggregateFn = Literal["count", "min", "max", "sum", "avg"]
AggregateCompareOp = Literal["eq", "ne", "lt", "lte", "gt", "gte"]

SCALAR_OPS: tuple[str, ...] = (
    "eq", "ne", "lt", "lte", "gt", "gte",
    "in", "not_in", "contains", "starts_with", "is_null",
)
AGGREGATE_FNS: tuple[str, ...] = ("count", "min", "max", "sum", "avg")
AGGREGATE_COMPARE_OPS: tuple[str, ...] = ("eq", "ne", "lt", "lte", "gt", "gte")


@dataclass(frozen=True)
class RelativeDate:
    """`as_of_date + offset_days`, resolved at run time."""

    offset_days: int

    def resolve(self, as_of_date: date) -> date:
        return as_of_date + timedelta(days=self.offset_days)


@dataclass(frozen=True)
class FieldCondition:
    """A condition on a scalar field of the entity being filtered."""

    field: str
    op: ScalarOp
    value: Any
    kind: Literal["field"] = "field"


@dataclass(frozen=True)
class AggregateCondition:
    """A filter on an aggregation across a one-hop related entity."""

    relationship: str
    fn: AggregateFn
    aggregate_field: str | None
    sub_filters: tuple[FieldCondition, ...]
    compare_op: AggregateCompareOp
    compare_value: float
    kind: Literal["aggregate"] = "aggregate"


Condition = Union[FieldCondition, AggregateCondition]


@dataclass(frozen=True)
class AggregateColumn:
    """A derived column displayed alongside the root entity's fields."""

    label: str
    relationship: str
    fn: AggregateFn
    aggregate_field: str | None
    sub_filters: tuple[FieldCondition, ...] = ()


@dataclass(frozen=True)
class Report:
    """Full report configuration."""

    name: str
    description: str
    root_entity: str
    conditions: tuple[Condition, ...] = field(default_factory=tuple)
    columns: tuple[str, ...] = field(default_factory=tuple)
    aggregate_columns: tuple[AggregateColumn, ...] = field(default_factory=tuple)
    id: str | None = None
    created_by: str = ""
    created_at: str = ""
    updated_at: str = ""


_RELATIVE_DATE_MARKER = "relative_date"


def _serialize_value(value: Any) -> Any:
    if isinstance(value, RelativeDate):
        return {"_type": _RELATIVE_DATE_MARKER, "offset_days": value.offset_days}
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_serialize_value(v) for v in value]
    return value


def _deserialize_value(value: Any) -> Any:
    if isinstance(value, dict) and value.get("_type") == _RELATIVE_DATE_MARKER:
        return RelativeDate(offset_days=int(value["offset_days"]))
    if isinstance(value, list):
        return [_deserialize_value(v) for v in value]
    return value


def _field_to_json(condition: FieldCondition) -> dict[str, Any]:
    return {
        "kind": "field",
        "field": condition.field,
        "op": condition.op,
        "value": _serialize_value(condition.value),
    }


def _field_from_json(data: dict[str, Any]) -> FieldCondition:
    return FieldCondition(
        field=str(data["field"]),
        op=str(data["op"]),  # type: ignore[arg-type]
        value=_deserialize_value(data.get("value")),
    )


def _aggregate_condition_to_json(condition: AggregateCondition) -> dict[str, Any]:
    return {
        "kind": "aggregate",
        "relationship": condition.relationship,
        "fn": condition.fn,
        "aggregate_field": condition.aggregate_field,
        "sub_filters": [_field_to_json(f) for f in condition.sub_filters],
        "compare_op": condition.compare_op,
        "compare_value": condition.compare_value,
    }


def _aggregate_condition_from_json(data: dict[str, Any]) -> AggregateCondition:
    return AggregateCondition(
        relationship=str(data["relationship"]),
        fn=str(data["fn"]),  # type: ignore[arg-type]
        aggregate_field=(
            str(data["aggregate_field"]) if data.get("aggregate_field") else None
        ),
        sub_filters=tuple(
            _field_from_json(f) for f in (data.get("sub_filters") or [])
        ),
        compare_op=str(data["compare_op"]),  # type: ignore[arg-type]
        compare_value=float(data["compare_value"]),
    )


def _aggregate_column_to_json(col: AggregateColumn) -> dict[str, Any]:
    return {
        "label": col.label,
        "relationship": col.relationship,
        "fn": col.fn,
        "aggregate_field": col.aggregate_field,
        "sub_filters": [_field_to_json(f) for f in col.sub_filters],
    }


def _aggregate_column_from_json(data: dict[str, Any]) -> AggregateColumn:
    return AggregateColumn(
        label=str(data["label"]),
        relationship=str(data["relationship"]),
        fn=str(data["fn"]),  # type: ignore[arg-type]
        aggregate_field=(
            str(data["aggregate_field"]) if data.get("aggregate_field") else None
        ),
        sub_filters=tuple(
            _field_from_json(f) for f in (data.get("sub_filters") or [])
        ),
    )


def _condition_to_json(condition: Condition) -> dict[str, Any]:
    if isinstance(condition, FieldCondition):
        return _field_to_json(condition)
    return _aggregate_condition_to_json(condition)


def _condition_from_json(data: dict[str, Any]) -> Condition:
    kind = data.get("kind")
    if kind == "field":
        return _field_from_json(data)
    if kind == "aggregate":
        return _aggregate_condition_from_json(data)
    raise ValueError(f"Unknown condition kind: {kind!r}")


def report_to_json(report: Report) -> dict[str, Any]:
    """Serialize a `Report` to its JSON wire format."""
    return {
        "id": report.id,
        "name": report.name,
        "description": report.description,
        "root_entity": report.root_entity,
        "conditions": [_condition_to_json(c) for c in report.conditions],
        "columns": list(report.columns),
        "aggregate_columns": [_aggregate_column_to_json(c) for c in report.aggregate_columns],
        "created_by": report.created_by,
        "created_at": report.created_at,
        "updated_at": report.updated_at,
    }


def report_from_json(data: dict[str, Any]) -> Report:
    """Build a `Report` from its JSON wire format. Raises ValueError on bad input."""
    if not isinstance(data, dict):
        raise ValueError("Report payload must be an object")
    if not isinstance(data.get("name"), str) or not data["name"].strip():
        raise ValueError("Report 'name' is required")
    if not isinstance(data.get("root_entity"), str) or not data["root_entity"]:
        raise ValueError("Report 'root_entity' is required")

    return Report(
        id=str(data["id"]) if data.get("id") else None,
        name=str(data["name"]),
        description=str(data.get("description") or ""),
        root_entity=str(data["root_entity"]),
        conditions=tuple(_condition_from_json(c) for c in (data.get("conditions") or [])),
        columns=tuple(str(c) for c in (data.get("columns") or [])),
        aggregate_columns=tuple(
            _aggregate_column_from_json(c) for c in (data.get("aggregate_columns") or [])
        ),
        created_by=str(data.get("created_by") or ""),
        created_at=str(data.get("created_at") or ""),
        updated_at=str(data.get("updated_at") or ""),
    )


def report_to_dict(report: Report) -> dict[str, Any]:
    """Internal dict conversion (uses dataclass asdict — for debug/tests only)."""
    return asdict(report)
