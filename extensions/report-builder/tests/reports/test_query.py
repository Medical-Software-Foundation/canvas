"""Query builder tests — verify the generated SQL contains expected clauses.

Uses Django's `str(qs.query)` to inspect SQL without executing it.
"""

from datetime import date

from report_builder.reports.models import (
    AggregateColumn,
    AggregateCondition,
    FieldCondition,
    RelativeDate,
    Report,
)
from report_builder.reports.query import (
    MAX_ROWS,
    _resolve_value,
    build_queryset,
    serialize_row,
)
from report_builder.schemas.registry import ENTITY_REGISTRY


def _patient_report(**kw: object) -> Report:
    defaults: dict[str, object] = {
        "name": "T",
        "description": "",
        "root_entity": "patient",
        "conditions": (),
        "columns": (),
        "aggregate_columns": (),
    }
    defaults.update(kw)
    return Report(**defaults)  # type: ignore[arg-type]


def test_field_condition_emits_where_clause() -> None:
    report = _patient_report(
        conditions=(FieldCondition(field="active", op="eq", value=True),),
    )
    qs, ann = build_queryset(report, date(2026, 5, 22))
    sql = str(qs.query)
    assert '"active"' in sql.lower() or "active" in sql
    assert "true" in sql.lower() or "1" in sql
    assert ann == []


def test_field_condition_negation() -> None:
    report = _patient_report(
        conditions=(FieldCondition(field="active", op="ne", value=True),),
    )
    qs, _ = build_queryset(report, date(2026, 5, 22))
    sql = str(qs.query)
    assert "NOT" in sql


def test_aggregate_count_emits_having_clause() -> None:
    report = _patient_report(
        conditions=(
            AggregateCondition(
                relationship="appointments",
                fn="count",
                aggregate_field=None,
                sub_filters=(),
                compare_op="eq",
                compare_value=0,
            ),
        ),
    )
    qs, _ = build_queryset(report, date(2026, 5, 22))
    sql = str(qs.query)
    assert "COUNT" in sql.upper()


def test_aggregate_with_subfilter_includes_filter_clause() -> None:
    report = _patient_report(
        conditions=(
            AggregateCondition(
                relationship="appointments",
                fn="count",
                aggregate_field=None,
                sub_filters=(
                    FieldCondition(field="status", op="eq", value="confirmed"),
                ),
                compare_op="eq",
                compare_value=0,
            ),
        ),
    )
    qs, _ = build_queryset(report, date(2026, 5, 22))
    sql = str(qs.query)
    assert "COUNT" in sql.upper()
    assert "confirmed" in sql.lower()


def test_aggregate_column_adds_annotation() -> None:
    report = _patient_report(
        aggregate_columns=(
            AggregateColumn(
                label="last_appt",
                relationship="appointments",
                fn="max",
                aggregate_field="start_time",
                sub_filters=(),
            ),
        )
    )
    qs, ann = build_queryset(report, date(2026, 5, 22))
    assert len(ann) == 1
    label, name = ann[0]
    assert label == "last_appt"
    assert name.startswith("_agg_")
    sql = str(qs.query)
    assert "MAX" in sql.upper()


def test_relative_date_resolves_before_reaching_sql() -> None:
    as_of = date(2026, 5, 22)
    report = _patient_report(
        root_entity="appointment",
        conditions=(
            FieldCondition(
                field="start_time", op="gte", value=RelativeDate(offset_days=-90)
            ),
        ),
    )
    qs, _ = build_queryset(report, as_of)
    sql = str(qs.query)
    # the resolved date 2026-02-21 should appear in the rendered SQL
    assert "2026-02-21" in sql


def test_resolve_value_handles_lists() -> None:
    as_of = date(2026, 5, 22)
    out = _resolve_value([RelativeDate(offset_days=-1), "x"], as_of)
    assert out == [date(2026, 5, 21), "x"]


def test_resolve_value_passthrough_for_non_relative() -> None:
    assert _resolve_value(42, date(2026, 5, 22)) == 42
    assert _resolve_value("hello", date(2026, 5, 22)) == "hello"


def test_serialize_row_lifts_column_values() -> None:
    class FakeRow:
        id = "abc"
        dbid = 7
        first_name = "Jane"
        last_name = "Doe"
        _agg_xyz = 3

    entity = ENTITY_REGISTRY["patient"]
    row = serialize_row(FakeRow(), entity, ("first_name", "last_name"), [("count", "_agg_xyz")])
    assert row == {
        "id": "abc",
        "dbid": 7,
        "first_name": "Jane",
        "last_name": "Doe",
        "count": 3,
    }


def test_serialize_row_handles_dates() -> None:
    from datetime import datetime

    class FakeRow:
        id = "abc"
        dbid = 7
        start_time = datetime(2026, 5, 22, 10, 30)

    entity = ENTITY_REGISTRY["appointment"]
    row = serialize_row(FakeRow(), entity, ("start_time",), [])
    assert row["start_time"] == "2026-05-22T10:30:00"


def test_max_rows_constant_is_10000() -> None:
    assert MAX_ROWS == 10_000
