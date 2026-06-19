from datetime import date

from questionnaire_scoring_dashboard.services.metrics import compute_metrics


def _pts(*pairs):
    return [{"date": d, "value": v} for d, v in pairs]


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
