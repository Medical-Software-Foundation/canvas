from datetime import date

from questionnaire_scoring_dashboard.services.metrics import (
    compute_metrics,
    filter_by_range,
)


def _pts(*pairs):
    return [{"date": d, "value": v} for d, v in pairs]


def test_filter_by_range_inclusive_bounds():
    pts = _pts(("2026-01-01", 1), ("2026-02-01", 2), ("2026-03-01", 3))
    out = filter_by_range(pts, "2026-01-15", "2026-02-15")
    assert [p["value"] for p in out] == [2]


def test_filter_by_range_none_bounds_returns_all():
    pts = _pts(("2026-01-01", 1), ("2026-02-01", 2))
    assert filter_by_range(pts, None, None) == pts


def test_compute_metrics_full():
    pts = _pts(("2026-01-01", 20), ("2026-01-20", 16))
    m = compute_metrics(pts, as_of=date(2026, 2, 1))
    assert m["latest"] == 16.0
    assert m["change"] == -4.0
    assert m["days_since"] == 12
    assert m["total"] == 2


def test_compute_metrics_single_point_has_no_change():
    pts = _pts(("2026-01-20", 16))
    m = compute_metrics(pts, as_of=date(2026, 2, 1))
    assert m["latest"] == 16.0
    assert m["change"] is None
    assert m["total"] == 1


def test_compute_metrics_empty():
    m = compute_metrics([], as_of=date(2026, 2, 1))
    assert m == {"latest": None, "change": None, "days_since": None, "total": 0}
