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
    h.request.path_params = {}
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


def test_run_unknown_dataset_returns_400():
    h = _handler({"dataset_key": "nope", "measure_key": "total"})
    responses = h.run()
    assert responses[0].status_code == 400


def test_run_unknown_measure_returns_400():
    h = _handler({"dataset_key": "appointments", "measure_key": "nope", "group_by": "provider"})
    responses = h.run()
    assert responses[0].status_code == 400


def test_run_disallowed_operator_for_field_returns_400():
    body = {
        "dataset_key": "appointments",
        "measure_key": "total",
        "group_by": "provider",
        "filters": [{"field": "status", "operator": "gte", "values": ["x"]}],
    }
    h = _handler(body)
    responses = h.run()
    assert responses[0].status_code == 400


def test_create_report_returns_id():
    from unittest.mock import patch, MagicMock
    body = {"name": "No-shows", "category": "Operations", "visibility": "shared",
            "definition": {"dataset_key": "appointments", "measure_key": "no_show_rate"}}
    h = _handler(body)
    with patch("reporting.routes.reporting_api._current_staff_dbid", return_value=5), \
         patch("reporting.routes.reporting_api.svc_create") as mock_create:
        mock_create.return_value = MagicMock(dbid=42)
        responses = h.create_report()
    assert responses[0].data["id"] == 42


def test_list_reports_returns_summaries():
    from unittest.mock import patch, MagicMock
    h = _handler()
    row = MagicMock(dbid=1, category="Operations", visibility="shared", owner_id=5)
    row.name = "X"
    with patch("reporting.routes.reporting_api._current_staff_dbid", return_value=5), \
         patch("reporting.routes.reporting_api.svc_list_visible", return_value=[row]):
        responses = h.list_reports()
    assert responses[0].data["reports"][0]["id"] == 1
    assert "definition" not in responses[0].data["reports"][0]


def test_get_report_404_when_missing():
    from unittest.mock import patch
    h = _handler()
    h.request.path_params = {"report_id": "99"}
    with patch("reporting.routes.reporting_api._current_staff_dbid", return_value=5), \
         patch("reporting.routes.reporting_api.svc_get_visible", return_value=None):
        responses = h.get_report()
    assert responses[0].status_code == 404


def test_delete_report_conflict_returns_404():
    from unittest.mock import patch
    h = _handler()
    h.request.path_params = {"report_id": "9"}
    with patch("reporting.routes.reporting_api._current_staff_dbid", return_value=5), \
         patch("reporting.routes.reporting_api.svc_delete", return_value=False):
        responses = h.delete_report()
    assert responses[0].status_code == 404


def test_field_options_returns_options():
    from unittest.mock import patch
    h = _handler()
    h.request.query_params = {"dataset": "appointments", "field": "provider"}
    with patch("reporting.routes.reporting_api._field_options",
               return_value=[{"value": "p1", "label": "A Alvarez"}]):
        responses = h.field_options()
    assert responses[0].data["options"][0]["value"] == "p1"


def test_field_options_400_for_field_without_options():
    h = _handler()
    h.request.query_params = {"dataset": "appointments", "field": "status"}
    responses = h.field_options()
    assert responses[0].status_code == 400


def test_list_dashboards_returns_summaries():
    from unittest.mock import patch, MagicMock
    h = _handler()
    row = MagicMock(dbid=1, visibility="shared", owner_id=5,
                    layout={"widgets": [{"report_id": 9}]})
    row.name = "Ops"
    with patch("reporting.routes.reporting_api._current_staff_dbid", return_value=5), \
         patch("reporting.routes.reporting_api.dash_list_visible", return_value=[row]):
        responses = h.list_dashboards()
    assert responses[0].data["dashboards"][0]["widget_count"] == 1


def test_create_dashboard_returns_id():
    from unittest.mock import patch, MagicMock
    body = {"name": "Ops", "visibility": "shared",
            "layout": {"widgets": []}, "default_period": {}}
    h = _handler(body)
    with patch("reporting.routes.reporting_api._current_staff_dbid", return_value=5), \
         patch("reporting.routes.reporting_api.dash_create", return_value=MagicMock(dbid=7)):
        responses = h.create_dashboard()
    assert responses[0].data["id"] == 7


def test_get_dashboard_404_when_missing():
    from unittest.mock import patch
    h = _handler()
    h.request.path_params = {"dashboard_id": "99"}
    with patch("reporting.routes.reporting_api._current_staff_dbid", return_value=5), \
         patch("reporting.routes.reporting_api.dash_get_visible", return_value=None):
        responses = h.get_dashboard()
    assert responses[0].status_code == 404


def test_delete_dashboard_404_when_not_owner():
    from unittest.mock import patch
    h = _handler()
    h.request.path_params = {"dashboard_id": "7"}
    with patch("reporting.routes.reporting_api._current_staff_dbid", return_value=5), \
         patch("reporting.routes.reporting_api.dash_delete", return_value=False):
        responses = h.delete_dashboard()
    assert responses[0].status_code == 404
