"""Report validation — fail loudly *before* a bad config reaches the ORM.

Every field/relationship/op reference must resolve through the entity schema
registry. Values must match the declared field type. Aggregate conditions and
columns must point at a one-hop relationship from the root entity and an
aggregate field that exists on the *target* entity.

The validator returns a list of structured errors with a `path` and `message`,
so the UI can surface them next to the right input.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from report_builder.reports.models import (
    AGGREGATE_COMPARE_OPS,
    AGGREGATE_FNS,
    SCALAR_OPS,
    AggregateColumn,
    AggregateCondition,
    FieldCondition,
    RelativeDate,
    Report,
)
from report_builder.schemas.base import EntitySchema, FieldSchema
from report_builder.schemas.registry import ENTITY_REGISTRY


@dataclass(frozen=True)
class ValidationError:
    """A single, displayable validation problem."""

    path: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "message": self.message}


_LIST_OPS = {"in", "not_in"}
_BOOL_OPS = {"is_null"}
_STRING_ONLY_OPS = {"contains", "starts_with"}


def _check_value_type(field_schema: FieldSchema, op: str, value: Any, path: str) -> list[ValidationError]:
    if op in _BOOL_OPS:
        if not isinstance(value, bool):
            return [ValidationError(path, f"Operator '{op}' requires a boolean value")]
        return []

    if op in _LIST_OPS:
        if not isinstance(value, (list, tuple)):
            return [ValidationError(path, f"Operator '{op}' requires a list value")]
        errors: list[ValidationError] = []
        for i, item in enumerate(value):
            errors.extend(_check_scalar_type(field_schema, item, f"{path}[{i}]"))
        return errors

    if op in _STRING_ONLY_OPS:
        if field_schema.type != "string":
            return [
                ValidationError(
                    path,
                    f"Operator '{op}' only applies to string fields (got '{field_schema.type}')",
                )
            ]

    return _check_scalar_type(field_schema, value, path)


def _check_scalar_type(field_schema: FieldSchema, value: Any, path: str) -> list[ValidationError]:
    ftype = field_schema.type

    if ftype in ("date", "datetime"):
        if isinstance(value, RelativeDate):
            return []
        if isinstance(value, (date, datetime)):
            return []
        if isinstance(value, str):
            try:
                if ftype == "date":
                    date.fromisoformat(value)
                else:
                    datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return [ValidationError(path, f"Invalid {ftype} value: {value!r}")]
            return []
        return [ValidationError(path, f"Expected {ftype}, got {type(value).__name__}")]

    if ftype == "boolean":
        if isinstance(value, bool):
            return []
        return [ValidationError(path, f"Expected boolean, got {type(value).__name__}")]

    if ftype == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            return [ValidationError(path, f"Expected integer, got {type(value).__name__}")]
        return []

    if ftype == "decimal":
        if isinstance(value, bool):
            return [ValidationError(path, "Expected number, got bool")]
        if isinstance(value, (int, float)):
            return []
        return [ValidationError(path, f"Expected number, got {type(value).__name__}")]

    if ftype == "choice":
        if not isinstance(value, str):
            return [ValidationError(path, f"Expected string choice, got {type(value).__name__}")]
        allowed = {c for c, _ in (field_schema.choices or ())}
        if allowed and value not in allowed:
            return [ValidationError(path, f"Value {value!r} not in allowed choices for '{field_schema.name}'")]
        return []

    # string
    if not isinstance(value, str):
        return [ValidationError(path, f"Expected string, got {type(value).__name__}")]
    return []


def _validate_field_condition(
    entity: EntitySchema, condition: FieldCondition, path: str
) -> list[ValidationError]:
    errors: list[ValidationError] = []
    field_schema = entity.field(condition.field)
    if field_schema is None:
        return [
            ValidationError(
                f"{path}.field",
                f"Field '{condition.field}' is not defined on entity '{entity.key}'",
            )
        ]
    if not field_schema.filterable:
        errors.append(
            ValidationError(f"{path}.field", f"Field '{condition.field}' is not filterable")
        )

    if condition.op not in SCALAR_OPS:
        errors.append(ValidationError(f"{path}.op", f"Unknown operator '{condition.op}'"))
        return errors

    errors.extend(_check_value_type(field_schema, condition.op, condition.value, f"{path}.value"))
    return errors


def _validate_aggregate_condition(
    entity: EntitySchema, condition: AggregateCondition, path: str
) -> list[ValidationError]:
    errors: list[ValidationError] = []
    rel = entity.relationship(condition.relationship)
    if rel is None:
        return [
            ValidationError(
                f"{path}.relationship",
                f"Relationship '{condition.relationship}' is not defined on entity '{entity.key}'",
            )
        ]

    target = ENTITY_REGISTRY.get(rel.target_entity)
    if target is None:
        return [
            ValidationError(
                f"{path}.relationship",
                f"Target entity '{rel.target_entity}' is not in the registry",
            )
        ]

    if condition.fn not in AGGREGATE_FNS:
        errors.append(ValidationError(f"{path}.fn", f"Unknown aggregate function '{condition.fn}'"))

    if condition.fn == "count":
        if condition.aggregate_field is not None:
            errors.append(
                ValidationError(
                    f"{path}.aggregate_field",
                    "'count' aggregate must not specify an aggregate_field",
                )
            )
    else:
        if not condition.aggregate_field:
            errors.append(
                ValidationError(
                    f"{path}.aggregate_field",
                    f"Aggregate '{condition.fn}' requires an aggregate_field",
                )
            )
        else:
            agg_field = target.field(condition.aggregate_field)
            if agg_field is None:
                errors.append(
                    ValidationError(
                        f"{path}.aggregate_field",
                        f"Field '{condition.aggregate_field}' not defined on '{target.key}'",
                    )
                )
            elif condition.fn in ("sum", "avg") and agg_field.type not in ("integer", "decimal"):
                errors.append(
                    ValidationError(
                        f"{path}.aggregate_field",
                        f"'{condition.fn}' requires a numeric field (got '{agg_field.type}')",
                    )
                )

    if condition.compare_op not in AGGREGATE_COMPARE_OPS:
        errors.append(
            ValidationError(
                f"{path}.compare_op", f"Unknown compare operator '{condition.compare_op}'"
            )
        )

    if not isinstance(condition.compare_value, (int, float)) or isinstance(
        condition.compare_value, bool
    ):
        errors.append(
            ValidationError(f"{path}.compare_value", "compare_value must be a number")
        )

    for i, sub in enumerate(condition.sub_filters):
        errors.extend(_validate_field_condition(target, sub, f"{path}.sub_filters[{i}]"))

    return errors


def _validate_aggregate_column(
    entity: EntitySchema, col: AggregateColumn, path: str
) -> list[ValidationError]:
    errors: list[ValidationError] = []
    if not col.label.strip():
        errors.append(ValidationError(f"{path}.label", "Computed column 'label' is required"))

    rel = entity.relationship(col.relationship)
    if rel is None:
        return errors + [
            ValidationError(
                f"{path}.relationship",
                f"Relationship '{col.relationship}' is not defined on entity '{entity.key}'",
            )
        ]

    target = ENTITY_REGISTRY.get(rel.target_entity)
    if target is None:
        return errors + [
            ValidationError(
                f"{path}.relationship",
                f"Target entity '{rel.target_entity}' is not in the registry",
            )
        ]

    if col.fn not in AGGREGATE_FNS:
        errors.append(ValidationError(f"{path}.fn", f"Unknown aggregate function '{col.fn}'"))

    if col.fn == "count":
        if col.aggregate_field is not None:
            errors.append(
                ValidationError(
                    f"{path}.aggregate_field",
                    "'count' aggregate must not specify an aggregate_field",
                )
            )
    else:
        if not col.aggregate_field:
            errors.append(
                ValidationError(
                    f"{path}.aggregate_field",
                    f"Aggregate '{col.fn}' requires an aggregate_field",
                )
            )
        else:
            agg_field = target.field(col.aggregate_field)
            if agg_field is None:
                errors.append(
                    ValidationError(
                        f"{path}.aggregate_field",
                        f"Field '{col.aggregate_field}' not defined on '{target.key}'",
                    )
                )
            elif col.fn in ("sum", "avg") and agg_field.type not in ("integer", "decimal"):
                errors.append(
                    ValidationError(
                        f"{path}.aggregate_field",
                        f"'{col.fn}' requires a numeric field (got '{agg_field.type}')",
                    )
                )

    for i, sub in enumerate(col.sub_filters):
        errors.extend(_validate_field_condition(target, sub, f"{path}.sub_filters[{i}]"))

    return errors


def validate_report(report: Report) -> list[ValidationError]:
    """Validate a fully-deserialized Report. Returns an empty list when valid."""
    errors: list[ValidationError] = []

    if not report.name.strip():
        errors.append(ValidationError("name", "Report name is required"))

    entity = ENTITY_REGISTRY.get(report.root_entity)
    if entity is None:
        errors.append(
            ValidationError("root_entity", f"Unknown entity '{report.root_entity}'")
        )
        return errors

    for i, col in enumerate(report.columns):
        f = entity.field(col)
        if f is None:
            errors.append(
                ValidationError(f"columns[{i}]", f"Column '{col}' is not defined on '{entity.key}'")
            )
        elif not f.selectable_column:
            errors.append(
                ValidationError(f"columns[{i}]", f"Column '{col}' is not selectable")
            )

    for i, cond in enumerate(report.conditions):
        if isinstance(cond, FieldCondition):
            errors.extend(_validate_field_condition(entity, cond, f"conditions[{i}]"))
        elif isinstance(cond, AggregateCondition):
            errors.extend(_validate_aggregate_condition(entity, cond, f"conditions[{i}]"))
        else:
            errors.append(  # type: ignore[unreachable]
                ValidationError(f"conditions[{i}]", f"Unsupported condition: {type(cond).__name__}")
            )

    for i, agg_col in enumerate(report.aggregate_columns):
        errors.extend(_validate_aggregate_column(entity, agg_col, f"aggregate_columns[{i}]"))

    return errors
