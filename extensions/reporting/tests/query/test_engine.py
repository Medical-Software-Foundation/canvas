# tests/query/test_engine.py
from __future__ import annotations

from datetime import date

from reporting.query.engine import ReportQuery, run_report
from reporting.query.filters import FilterClause
from reporting.query.periods import PeriodSpec


def _fake_executor(calls):
    """Returns an executor that records calls and returns canned grouped rows per period."""
    # canned rows keyed by period label
    canned = {
        "May 2026": [
            {"provider__id": "p1", "provider__first_name": "A", "provider__last_name": "Alvarez",
             "no_show_rate__num": 12, "no_show_rate__den": 100},
        ],
        "Jun 2026": [
            {"provider__id": "p1", "provider__first_name": "A", "provider__last_name": "Alvarez",
             "no_show_rate__num": 11, "no_show_rate__den": 100},
        ],
    }

    def executor(model, lookups, group_paths, count_specs):
        calls.append({"model": model.__name__, "lookups": lookups,
                      "group_paths": group_paths, "count_specs": count_specs})
        # the date range lookups encode the period; map by start_time month
        start = lookups["start_time__gte"]
        label = "Jun 2026" if start.month == 6 else "May 2026"
        return canned[label]

    return executor


def test_run_report_groups_and_computes_ratio_per_period():
    calls = []
    q = ReportQuery(
        dataset_key="appointments",
        filters=[FilterClause(orm_path="status", operator="is_one_of",
                              values=["noshowed", "cancelled"])],
        measure_key="no_show_rate",
        group_by="provider",
        period=PeriodSpec(granularity="month", count=2, include_rolling_12=False),
    )
    result = run_report(q, anchor=date(2026, 6, 15), executor=_fake_executor(calls))

    assert result["measure"] == "No-show rate (%)"
    assert result["periods"] == ["May 2026", "Jun 2026"]
    # one group row, with a value per period
    assert len(result["rows"]) == 1
    row = result["rows"][0]
    assert row["group_label"] == "A Alvarez"
    assert row["values"] == {"May 2026": 12.0, "Jun 2026": 11.0}


def test_run_report_runs_one_query_per_period():
    calls = []
    q = ReportQuery(
        dataset_key="appointments", filters=[], measure_key="no_show_rate",
        group_by="provider",
        period=PeriodSpec(granularity="month", count=2, include_rolling_12=False),
    )
    run_report(q, anchor=date(2026, 6, 15), executor=_fake_executor(calls))
    assert len(calls) == 2  # one ORM query per period window


def test_run_report_merges_date_range_into_lookups():
    calls = []
    q = ReportQuery(
        dataset_key="appointments", filters=[], measure_key="total",
        group_by="provider",
        period=PeriodSpec(granularity="month", count=1, include_rolling_12=False),
    )
    # total measure -> executor returns rows with total__all
    def executor(model, lookups, group_paths, count_specs):
        calls.append(lookups)
        return [{"provider__id": "p1", "provider__first_name": "A",
                 "provider__last_name": "B", "total__all": 50}]

    result = run_report(q, anchor=date(2026, 6, 15), executor=executor)
    assert "start_time__gte" in calls[0] and "start_time__lt" in calls[0]
    assert result["rows"][0]["values"]["Jun 2026"] == 50
