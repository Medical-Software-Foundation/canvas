"""Test `validate_report` — every bad input must surface a structured error."""

from report_builder.reports.models import (
    AggregateColumn,
    AggregateCondition,
    FieldCondition,
    RelativeDate,
    Report,
)
from report_builder.reports.validate import ValidationError, validate_report


def _patient_report(**overrides: object) -> Report:
    defaults: dict[str, object] = {
        "name": "Test report",
        "description": "",
        "root_entity": "patient",
        "conditions": (),
        "columns": (),
        "aggregate_columns": (),
    }
    defaults.update(overrides)
    return Report(**defaults)  # type: ignore[arg-type]


def test_valid_minimal_report_is_clean() -> None:
    assert validate_report(_patient_report()) == []


def test_missing_name_is_flagged() -> None:
    errors = validate_report(_patient_report(name=" "))
    assert any(e.path == "name" for e in errors)


def test_unknown_root_entity_is_flagged() -> None:
    errors = validate_report(_patient_report(root_entity="alien"))
    assert errors == [ValidationError("root_entity", "Unknown entity 'alien'")]


def test_unknown_column_is_flagged() -> None:
    errors = validate_report(_patient_report(columns=("nope",)))
    assert any("columns[0]" in e.path for e in errors)


def test_unknown_field_in_condition_is_flagged() -> None:
    errors = validate_report(
        _patient_report(
            conditions=(FieldCondition(field="nonexistent", op="eq", value="x"),)
        )
    )
    assert any(e.path == "conditions[0].field" for e in errors)


def test_unknown_operator_is_flagged() -> None:
    errors = validate_report(
        _patient_report(
            conditions=(FieldCondition(field="first_name", op="bogus", value="x"),)  # type: ignore[arg-type]
        )
    )
    assert any(e.path == "conditions[0].op" for e in errors)


def test_type_mismatch_is_flagged_for_integer_field() -> None:
    errors = validate_report(
        _patient_report(
            root_entity="appointment",
            conditions=(FieldCondition(field="duration_minutes", op="eq", value="not a number"),),
        )
    )
    assert any(e.path == "conditions[0].value" for e in errors)


def test_in_operator_requires_list() -> None:
    errors = validate_report(
        _patient_report(
            conditions=(FieldCondition(field="first_name", op="in", value="single"),)
        )
    )
    assert any("conditions[0].value" in e.path for e in errors)


def test_is_null_requires_boolean() -> None:
    errors = validate_report(
        _patient_report(
            conditions=(FieldCondition(field="first_name", op="is_null", value="yes"),)
        )
    )
    assert any("conditions[0].value" in e.path for e in errors)


def test_contains_rejected_on_non_string_field() -> None:
    errors = validate_report(
        _patient_report(
            root_entity="appointment",
            conditions=(FieldCondition(field="duration_minutes", op="contains", value="x"),),
        )
    )
    assert any("conditions[0].value" in e.path for e in errors)


def test_relative_date_accepted_for_date_field() -> None:
    errors = validate_report(
        _patient_report(
            root_entity="appointment",
            conditions=(
                FieldCondition(field="start_time", op="gte", value=RelativeDate(offset_days=-90)),
            ),
        )
    )
    assert errors == []


def test_choice_value_must_match() -> None:
    errors = validate_report(
        _patient_report(
            root_entity="appointment",
            conditions=(FieldCondition(field="status", op="eq", value="not-a-status"),),
        )
    )
    assert any("conditions[0].value" in e.path for e in errors)


def test_aggregate_count_must_not_have_field() -> None:
    errors = validate_report(
        _patient_report(
            conditions=(
                AggregateCondition(
                    relationship="appointments",
                    fn="count",
                    aggregate_field="start_time",
                    sub_filters=(),
                    compare_op="gte",
                    compare_value=1,
                ),
            )
        )
    )
    assert any("aggregate_field" in e.path for e in errors)


def test_aggregate_max_requires_field() -> None:
    errors = validate_report(
        _patient_report(
            conditions=(
                AggregateCondition(
                    relationship="appointments",
                    fn="max",
                    aggregate_field=None,
                    sub_filters=(),
                    compare_op="gte",
                    compare_value=1,
                ),
            )
        )
    )
    assert any("aggregate_field" in e.path for e in errors)


def test_aggregate_sum_requires_numeric_field() -> None:
    errors = validate_report(
        _patient_report(
            conditions=(
                AggregateCondition(
                    relationship="appointments",
                    fn="sum",
                    aggregate_field="status",
                    sub_filters=(),
                    compare_op="gte",
                    compare_value=1,
                ),
            )
        )
    )
    assert any("aggregate_field" in e.path for e in errors)


def test_aggregate_relationship_must_exist() -> None:
    errors = validate_report(
        _patient_report(
            conditions=(
                AggregateCondition(
                    relationship="unknown",
                    fn="count",
                    aggregate_field=None,
                    sub_filters=(),
                    compare_op="gte",
                    compare_value=1,
                ),
            )
        )
    )
    assert any("relationship" in e.path for e in errors)


def test_aggregate_sub_filter_field_must_exist_on_target() -> None:
    errors = validate_report(
        _patient_report(
            conditions=(
                AggregateCondition(
                    relationship="appointments",
                    fn="count",
                    aggregate_field=None,
                    sub_filters=(
                        FieldCondition(field="not_on_appointment", op="eq", value="x"),
                    ),
                    compare_op="gte",
                    compare_value=1,
                ),
            )
        )
    )
    assert any("sub_filters[0]" in e.path for e in errors)


def test_aggregate_column_requires_label() -> None:
    errors = validate_report(
        _patient_report(
            aggregate_columns=(
                AggregateColumn(
                    label="",
                    relationship="appointments",
                    fn="count",
                    aggregate_field=None,
                ),
            )
        )
    )
    assert any("label" in e.path for e in errors)


def test_unknown_aggregate_function_is_flagged() -> None:
    errors = validate_report(
        _patient_report(
            conditions=(
                AggregateCondition(
                    relationship="appointments",
                    fn="bogus",  # type: ignore[arg-type]
                    aggregate_field=None,
                    sub_filters=(),
                    compare_op="gte",
                    compare_value=1,
                ),
            )
        )
    )
    assert any(e.path.endswith(".fn") for e in errors)


def test_compare_value_must_be_number() -> None:
    errors = validate_report(
        _patient_report(
            conditions=(
                AggregateCondition(
                    relationship="appointments",
                    fn="count",
                    aggregate_field=None,
                    sub_filters=(),
                    compare_op="gte",
                    compare_value="not a number",  # type: ignore[arg-type]
                ),
            )
        )
    )
    assert any("compare_value" in e.path for e in errors)
