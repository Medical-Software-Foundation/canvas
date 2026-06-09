# tests/routes/test_reporting_api.py
from __future__ import annotations

from unittest.mock import MagicMock, patch

from reporting.routes.reporting_api import ReportingAPI


def _handler(body=None):
    h = ReportingAPI.__new__(ReportingAPI)
    h.request = MagicMock()
    h.request.headers = {"canvas-logged-in-user-id": "uid"}
    h.request.query_params = {}
    h.request.json = MagicMock(return_value=body or {})
    return h


def test_home_returns_html():
    h = _handler()
    responses = h.home()
    assert responses[0].content_type == "text/html"


def test_app_css_served_as_css():
    h = _handler()
    responses = h.app_css()
    assert responses[0].content_type == "text/css"


def test_datasets_route_lists_datasets_json():
    h = _handler()
    responses = h.datasets()
    data = responses[0].data
    assert any(d["key"] == "appointments" for d in data["datasets"])


def test_run_route_builds_query_and_returns_engine_result():
    body = {
        "dataset_key": "appointments",
        "measure_key": "no_show_rate",
        "group_by": "provider",
        "filters": [{"field": "status", "operator": "is_one_of",
                     "values": ["noshowed", "cancelled"]}],
        "period": {"granularity": "month", "count": 3, "include_rolling_12": False},
    }
    h = _handler(body)
    fake_result = {"rows": [], "periods": ["Apr 2026"]}
    with patch("reporting.routes.reporting_api.run_report", return_value=fake_result) as mock_run:
        responses = h.run()
    assert responses[0].data == fake_result
    # the handler must have resolved the field's orm_path for the filter clause
    called_query = mock_run.call_args.args[0]
    assert called_query.dataset_key == "appointments"
    assert called_query.filters[0].orm_path == "status"
    assert called_query.period.count == 3
