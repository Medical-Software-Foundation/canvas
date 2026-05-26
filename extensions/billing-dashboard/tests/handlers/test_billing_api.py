"""Tests for BillingDashboardAPI handler and mock data helpers."""

import json
from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest

from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response

from billing_dashboard.data import mock
from billing_dashboard.data.cms_rates import CMS_PRIMARY_BENCHMARK
from billing_dashboard.handlers.billing_api import BillingDashboardAPI


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_event(path: str = "/dashboard", query_string: str = "") -> MagicMock:
    event = MagicMock()
    event.context = {
        "method": "GET",
        "path": path,
        "query_string": query_string,
        "body": "",
        "headers": {"canvas-logged-in-user-id": "staff-abc-123"},
    }
    return event


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_cms_99214_rate_value() -> None:
    assert CMS_PRIMARY_BENCHMARK == 128.94


# ---------------------------------------------------------------------------
# _financial_overview_data
# ---------------------------------------------------------------------------


class TestFinancialOverviewData:

    def test_returns_summary_keys(self) -> None:
        data = mock.financial_overview()
        summary = data["summary"]
        assert "last_month_collected" in summary
        assert "this_month_to_date" in summary
        assert "next_month_projected" in summary
        assert "claim_acceptance_rate" in summary
        assert "last_month_trend_pct" in summary
        assert "next_month_appt_count" in summary

    def test_returns_daily_data(self) -> None:
        data = mock.financial_overview()
        assert len(data["daily"]) > 0
        entry = data["daily"][0]
        assert "date" in entry
        assert "visits" in entry
        assert "revenue" in entry

    def test_returns_monthly_data(self) -> None:
        data = mock.financial_overview()
        assert len(data["monthly"]) == 12
        entry = data["monthly"][0]
        assert "month" in entry
        assert "revenue" in entry

    def test_returns_insights(self) -> None:
        data = mock.financial_overview()
        assert len(data["insights"]) > 0
        insight = data["insights"][0]
        assert "severity" in insight
        assert "title" in insight
        assert "description" in insight
        assert "tag" in insight

    def test_insight_severities_are_valid(self) -> None:
        data = mock.financial_overview()
        valid = {"critical", "warning", "info"}
        for insight in data["insights"]:
            assert insight["severity"] in valid

    def test_summary_values_are_numeric(self) -> None:
        data = mock.financial_overview()
        s = data["summary"]
        assert isinstance(s["last_month_collected"], (int, float))
        assert isinstance(s["this_month_to_date"], (int, float))
        assert isinstance(s["next_month_projected"], (int, float))
        assert isinstance(s["claim_acceptance_rate"], (int, float))
        assert isinstance(s["last_month_trend_pct"], (int, float))
        assert isinstance(s["next_month_appt_count"], int)


# ---------------------------------------------------------------------------
# _payer_analysis_data
# ---------------------------------------------------------------------------


class TestPayerAnalysisData:

    def test_returns_payers_list(self) -> None:
        data = mock.payer_analysis()
        assert "payers" in data
        assert len(data["payers"]) == 6

    def test_payer_entry_keys(self) -> None:
        payer = mock.payer_analysis()["payers"][0]
        assert "name" in payer
        assert "total_reimbursement" in payer
        assert "acceptance_rate" in payer
        assert "avg_99214" in payer
        assert "cms_delta" in payer

    def test_payer_values_are_numeric(self) -> None:
        for payer in mock.payer_analysis()["payers"]:
            assert isinstance(payer["total_reimbursement"], (int, float))
            assert isinstance(payer["acceptance_rate"], (int, float))
            assert isinstance(payer["avg_99214"], (int, float))
            assert isinstance(payer["cms_delta"], (int, float))

    def test_medicare_delta_is_zero(self) -> None:
        payers = mock.payer_analysis()["payers"]
        medicare = next(p for p in payers if p["name"] == "Medicare")
        assert medicare["cms_delta"] == 0.00
        assert medicare["avg_99214"] == CMS_PRIMARY_BENCHMARK


# ---------------------------------------------------------------------------
# _trends_data
# ---------------------------------------------------------------------------


class TestTrendsData:

    def test_returns_cpt_codes(self) -> None:
        data = mock.trends()
        assert "cpt_codes" in data
        assert len(data["cpt_codes"]) == 6

    def test_cpt_entry_keys(self) -> None:
        cpt = mock.trends()["cpt_codes"][0]
        assert "code" in cpt
        assert "description" in cpt
        assert "your_avg" in cpt
        assert "cms_rate" in cpt
        assert "trend" in cpt

    def test_trend_values_are_valid(self) -> None:
        for cpt in mock.trends()["cpt_codes"]:
            assert cpt["trend"] in (-1, 0, 1)

    def test_returns_monthly_avg(self) -> None:
        data = mock.trends()
        assert len(data["monthly_avg"]) == 12
        entry = data["monthly_avg"][0]
        assert "month" in entry
        assert "avg" in entry

    def test_cms_benchmark_matches_constant(self) -> None:
        data = mock.trends()
        assert data["cms_benchmark"] == CMS_PRIMARY_BENCHMARK

    def test_99214_cms_rate_matches_constant(self) -> None:
        cpts = mock.trends()["cpt_codes"]
        c99214 = next(c for c in cpts if c["code"] == "99214")
        assert c99214["cms_rate"] == CMS_PRIMARY_BENCHMARK


# ---------------------------------------------------------------------------
# BillingDashboardAPI.dashboard / styles_css / main_js
# ---------------------------------------------------------------------------


class TestDashboardEndpoint:

    @patch("billing_dashboard.handlers.billing_api.render_to_string")
    def test_returns_html_response(self, mock_render: MagicMock) -> None:
        mock_render.return_value = "<html>test</html>"
        handler = BillingDashboardAPI(event=_make_event("/dashboard"))

        result = handler.dashboard()

        assert len(result) == 1
        resp = result[0]
        assert isinstance(resp, HTMLResponse)
        assert resp.status_code == HTTPStatus.OK
        assert resp.content == b"<html>test</html>"
        mock_render.assert_called_once_with("templates/page.html")

    @patch("billing_dashboard.handlers.billing_api.render_to_string")
    def test_handles_none_html(self, mock_render: MagicMock) -> None:
        mock_render.return_value = None
        handler = BillingDashboardAPI(event=_make_event("/dashboard"))

        result = handler.dashboard()

        assert result[0].content == b""


class TestStylesEndpoint:

    @patch("billing_dashboard.handlers.billing_api.render_to_string")
    def test_returns_css_response(self, mock_render: MagicMock) -> None:
        mock_render.return_value = "body { color: red; }"
        handler = BillingDashboardAPI(event=_make_event("/styles.css"))

        result = handler.styles_css()

        assert len(result) == 1
        resp = result[0]
        assert isinstance(resp, Response)
        assert resp.status_code == HTTPStatus.OK
        assert resp.content == b"body { color: red; }"
        assert resp.headers["Content-Type"] == "text/css"
        mock_render.assert_called_once_with("static/css/styles.css")


class TestMainJsEndpoint:

    @patch("billing_dashboard.handlers.billing_api.render_to_string")
    def test_returns_js_response(self, mock_render: MagicMock) -> None:
        mock_render.return_value = "console.log('hi');"
        handler = BillingDashboardAPI(event=_make_event("/main.js"))

        result = handler.main_js()

        assert len(result) == 1
        resp = result[0]
        assert isinstance(resp, Response)
        assert resp.status_code == HTTPStatus.OK
        assert resp.content == b"console.log('hi');"
        assert resp.headers["Content-Type"] == "text/javascript"
        mock_render.assert_called_once_with("static/js/main.js")


# ---------------------------------------------------------------------------
# BillingDashboardAPI.metrics
# ---------------------------------------------------------------------------


class TestMetricsEndpoint:

    def _handler_for_tab(self, tab: str | None = None) -> BillingDashboardAPI:
        qs = f"tab={tab}" if tab else ""
        return BillingDashboardAPI(event=_make_event("/api/metrics", qs))

    def test_defaults_to_overview(self) -> None:
        with patch("billing_dashboard.handlers.billing_api.build_overview") as mock_build:
            mock_build.return_value = {"summary": {}, "daily": {"source": "real", "data": []},
                                       "monthly": {"source": "real", "data": []},
                                       "insights": {"source": "real", "data": []}}
            handler = self._handler_for_tab()
            result = handler.metrics()
            data = json.loads(result[0].content)
            assert "summary" in data

    def test_overview_tab(self) -> None:
        with patch("billing_dashboard.handlers.billing_api.build_overview") as mock_build:
            mock_build.return_value = {
                "summary": {"last_month_collected": {"value": 100.0, "source": "real"}},
                "daily": {"source": "real", "data": []},
                "monthly": {"source": "real", "data": []},
                "insights": {"source": "real", "data": []},
            }
            handler = self._handler_for_tab("overview")
            result = handler.metrics()
            data = json.loads(result[0].content)
            assert data["summary"]["last_month_collected"]["source"] == "real"
            assert "daily" in data
            assert "monthly" in data
            assert "insights" in data

    def test_payer_tab(self) -> None:
        with patch("billing_dashboard.handlers.billing_api.build_payer") as mock_build:
            mock_build.return_value = {"payers": {"source": "real", "data": []}}
            handler = self._handler_for_tab("payer")
            result = handler.metrics()
            data = json.loads(result[0].content)
            assert data["payers"]["source"] == "real"

    def test_trends_tab(self) -> None:
        with patch("billing_dashboard.handlers.billing_api.build_trends") as mock_build:
            mock_build.return_value = {
                "cpt_codes": {"source": "real", "data": []},
                "monthly_avg": {"source": "real", "data": []},
                "cms_benchmark": 128.94,
            }
            handler = self._handler_for_tab("trends")
            result = handler.metrics()
            data = json.loads(result[0].content)
            assert data["cpt_codes"]["source"] == "real"
            assert data["cms_benchmark"] == 128.94

    def test_unknown_tab(self) -> None:
        handler = self._handler_for_tab("invalid")
        result = handler.metrics()
        data = json.loads(result[0].content)
        assert data == {"message": "Unknown tab"}

    def test_returns_json_response(self) -> None:
        with patch("billing_dashboard.handlers.billing_api.build_overview") as mock_build:
            mock_build.return_value = {"summary": {}, "daily": {"source": "real", "data": []},
                                       "monthly": {"source": "real", "data": []},
                                       "insights": {"source": "real", "data": []}}
            handler = self._handler_for_tab("overview")
            result = handler.metrics()
            assert len(result) == 1
            assert isinstance(result[0], JSONResponse)
            assert result[0].status_code == HTTPStatus.OK


