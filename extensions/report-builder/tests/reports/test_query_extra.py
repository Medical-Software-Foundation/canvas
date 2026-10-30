"""Extra query-builder coverage — safe_run, paging."""

from datetime import date
from unittest.mock import MagicMock, patch


from report_builder.reports.models import (
    AggregateCondition,
    FieldCondition,
    Report,
)
from report_builder.reports.query import (
    MAX_ROWS,
    _coerce_for_json,
    page_queryset,
    safe_run,
)


def _patient_report(**kw: object) -> Report:
    base: dict[str, object] = {
        "name": "T",
        "description": "",
        "root_entity": "patient",
        "conditions": (),
        "columns": (),
        "aggregate_columns": (),
    }
    base.update(kw)
    return Report(**base)  # type: ignore[arg-type]


def test_is_null_emits_isnull_lookup() -> None:
    from report_builder.reports.query import build_queryset

    report = _patient_report(
        conditions=(FieldCondition(field="first_name", op="is_null", value=True),)
    )
    qs, _ = build_queryset(report, date(2026, 5, 22))
    sql = str(qs.query)
    assert "IS NULL" in sql.upper()


def test_in_op_emits_in_lookup() -> None:
    from report_builder.reports.query import build_queryset

    report = _patient_report(
        conditions=(FieldCondition(field="first_name", op="in", value=["A", "B"]),)
    )
    qs, _ = build_queryset(report, date(2026, 5, 22))
    sql = str(qs.query)
    assert " IN " in sql.upper()


def test_not_in_op_emits_negated_in() -> None:
    from report_builder.reports.query import build_queryset

    report = _patient_report(
        conditions=(FieldCondition(field="first_name", op="not_in", value=["A"]),)
    )
    qs, _ = build_queryset(report, date(2026, 5, 22))
    sql = str(qs.query)
    assert "NOT" in sql


def test_contains_op_emits_icontains() -> None:
    from report_builder.reports.query import build_queryset

    report = _patient_report(
        conditions=(FieldCondition(field="first_name", op="contains", value="ane"),)
    )
    qs, _ = build_queryset(report, date(2026, 5, 22))
    sql = str(qs.query)
    assert "LIKE" in sql.upper()


def test_aggregate_compare_ne_is_negated() -> None:
    from report_builder.reports.query import build_queryset

    report = _patient_report(
        conditions=(
            AggregateCondition(
                relationship="appointments",
                fn="count",
                aggregate_field=None,
                sub_filters=(),
                compare_op="ne",
                compare_value=0,
            ),
        )
    )
    qs, _ = build_queryset(report, date(2026, 5, 22))
    sql = str(qs.query)
    assert "NOT" in sql


def test_aggregate_with_lt_compare() -> None:
    from report_builder.reports.query import build_queryset

    report = _patient_report(
        conditions=(
            AggregateCondition(
                relationship="appointments",
                fn="count",
                aggregate_field=None,
                sub_filters=(),
                compare_op="lt",
                compare_value=3,
            ),
        )
    )
    qs, _ = build_queryset(report, date(2026, 5, 22))
    sql = str(qs.query)
    assert "<" in sql


def test_page_queryset_clamps_per_page_and_page() -> None:
    fake_qs = MagicMock()
    fake_qs.count.return_value = 25
    fake_qs.__getitem__.return_value = [object(), object()]

    rows, total, too_large = page_queryset(fake_qs, page=0, per_page=200)

    assert total == 25
    assert too_large is False
    assert rows == [object(), object()] or len(rows) == 2
    # Per-page clamped to <= 100, page clamped to >= 1 — slice arguments verify
    slice_call = fake_qs.__getitem__.call_args.args[0]
    assert slice_call.start == 0
    assert slice_call.stop == 100


def test_page_queryset_flags_too_large() -> None:
    fake_qs = MagicMock()
    fake_qs.count.return_value = MAX_ROWS + 1
    rows, total, too_large = page_queryset(fake_qs, page=1, per_page=100)
    assert rows == []
    assert too_large is True
    assert total == MAX_ROWS + 1


@patch("report_builder.reports.query.build_queryset")
def test_safe_run_returns_too_large_payload(
    mock_build: MagicMock,
) -> None:
    fake_qs = MagicMock()
    fake_qs.count.return_value = MAX_ROWS + 5
    mock_build.return_value = (fake_qs, [])

    result = safe_run(_patient_report(), date(2026, 5, 22), page=1, per_page=100)
    assert result["too_large"] is True
    assert result["rows"] == []
    assert result["total"] == MAX_ROWS + 5


@patch("report_builder.reports.query.build_queryset")
def test_safe_run_returns_rows_and_annotations(
    mock_build: MagicMock,
) -> None:
    row = MagicMock()
    row.id = "abc"
    row.dbid = 1
    row.first_name = "Jane"
    row._agg_z = 3

    fake_qs = MagicMock()
    fake_qs.count.return_value = 1
    fake_qs.__getitem__.return_value = [row]
    mock_build.return_value = (fake_qs, [("appt_count", "_agg_z")])

    report = _patient_report(columns=("first_name",))
    result = safe_run(report, date(2026, 5, 22), page=1, per_page=100)
    assert result["too_large"] is False
    assert result["annotation_columns"] == ["appt_count"]
    assert result["rows"][0]["first_name"] == "Jane"
    assert result["rows"][0]["appt_count"] == 3


def test_coerce_for_json_handles_none() -> None:
    assert _coerce_for_json(None) is None


def test_coerce_for_json_passes_through_primitives() -> None:
    assert _coerce_for_json(42) == 42
    assert _coerce_for_json(3.14) == 3.14
    assert _coerce_for_json("x") == "x"
    assert _coerce_for_json(True) is True


def test_coerce_for_json_stringifies_other_types() -> None:
    class Other:
        def __str__(self) -> str:
            return "other"

    assert _coerce_for_json(Other()) == "other"
