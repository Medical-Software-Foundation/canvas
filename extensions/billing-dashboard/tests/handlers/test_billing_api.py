"""Tests for BillingDashboardAPI handler."""

import json
from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest

from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response

from billing_dashboard.data.cms_rates import CMS_PRIMARY_BENCHMARK
from billing_dashboard.handlers.billing_api import ASSET_VERSION, BillingDashboardAPI


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
    def test_version_sentinel_replaced(self, mock_render: MagicMock) -> None:
        mock_render.return_value = '<link href="styles.css?v=__VERSION__"><script src="main.js?v=__VERSION__">'
        handler = BillingDashboardAPI(event=_make_event("/dashboard"))

        result = handler.dashboard()

        body = result[0].content.decode()
        assert "__VERSION__" not in body
        assert f"styles.css?v={ASSET_VERSION}" in body
        assert f"main.js?v={ASSET_VERSION}" in body

    @patch("billing_dashboard.handlers.billing_api.render_to_string")
    def test_missing_template_returns_500(self, mock_render: MagicMock) -> None:
        mock_render.return_value = None
        handler = BillingDashboardAPI(event=_make_event("/dashboard"))

        result = handler.dashboard()

        assert result[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR


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

    @patch("billing_dashboard.handlers.billing_api.render_to_string")
    def test_missing_css_returns_500(self, mock_render: MagicMock) -> None:
        mock_render.return_value = None
        handler = BillingDashboardAPI(event=_make_event("/styles.css"))
        result = handler.styles_css()
        assert result[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR


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

    @patch("billing_dashboard.handlers.billing_api.render_to_string")
    def test_missing_js_returns_500(self, mock_render: MagicMock) -> None:
        mock_render.return_value = None
        handler = BillingDashboardAPI(event=_make_event("/main.js"))
        result = handler.main_js()
        assert result[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR


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
        assert result[0].status_code == HTTPStatus.BAD_REQUEST
        data = json.loads(result[0].content)
        assert data == {"error": "Unknown tab"}

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


