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
    def test_missing_template_propagates_filenotfound(self, mock_render: MagicMock) -> None:
        """render_to_string raises FileNotFoundError on missing templates;
        the handler must let it propagate to the SDK exception handler
        (and thus Sentry) rather than mask it as a swallowed 500."""
        mock_render.side_effect = FileNotFoundError("Template templates/page.html not found.")
        handler = BillingDashboardAPI(event=_make_event("/dashboard"))

        with pytest.raises(FileNotFoundError):
            handler.dashboard()


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
    def test_missing_css_propagates_filenotfound(self, mock_render: MagicMock) -> None:
        """Same reasoning as the dashboard test — a missing static asset is a
        packaging defect that must reach Sentry, not a runtime 500 to mask."""
        mock_render.side_effect = FileNotFoundError("Template static/css/styles.css not found.")
        handler = BillingDashboardAPI(event=_make_event("/styles.css"))

        with pytest.raises(FileNotFoundError):
            handler.styles_css()


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
    def test_missing_js_propagates_filenotfound(self, mock_render: MagicMock) -> None:
        """Same reasoning as the dashboard test — a missing static asset is a
        packaging defect that must reach Sentry, not a runtime 500 to mask."""
        mock_render.side_effect = FileNotFoundError("Template static/js/main.js not found.")
        handler = BillingDashboardAPI(event=_make_event("/main.js"))

        with pytest.raises(FileNotFoundError):
            handler.main_js()


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




# ---------------------------------------------------------------------------
# BillingDashboardAPI.claims / claims_csv (PLUGIN-213 / PLUGIN-223)
# ---------------------------------------------------------------------------


class TestClaimsEndpoints:

    @pytest.fixture(autouse=True)
    def viewer_tz(self):
        with patch(
            "billing_dashboard.handlers.billing_api.staff_timezone",
            return_value="America/New_York",
        ) as tz:
            yield tz

    def test_claims_and_csv_use_signed_in_staff_timezone(self, viewer_tz) -> None:
        with (
            patch("billing_dashboard.handlers.billing_api.build_claims") as mock_build,
            patch("billing_dashboard.handlers.billing_api.build_claims_csv") as mock_csv,
        ):
            mock_build.return_value = {"claims": []}
            mock_csv.return_value = ("", False)
            self._handler("/api/claims").claims()
            self._handler("/api/claims.csv").claims_csv()
        viewer_tz.assert_called_with("staff-abc-123")
        assert mock_build.call_args.kwargs["tz"] == "America/New_York"
        assert mock_csv.call_args.kwargs["tz"] == "America/New_York"

    def _handler(self, path: str, qs: str = "", secrets: dict | None = None) -> BillingDashboardAPI:
        return BillingDashboardAPI(event=_make_event(path, qs), secrets=secrets or {})

    def test_claims_passes_parsed_query_and_setting(self) -> None:
        with patch("billing_dashboard.handlers.billing_api.build_claims") as mock_build:
            mock_build.return_value = {"claims": []}
            handler = self._handler(
                "/api/claims",
                "sort=payer&dir=asc&window=30&queue=CashPay",
                secrets={"CLAIMS_BUSINESS_LINE_FILTER": "true"},
            )
            result = handler.claims()
        assert result[0].status_code == HTTPStatus.OK
        query, enabled = mock_build.call_args.args
        assert (query.sort, query.direction, query.window_days, query.queue) == (
            "payer", "asc", 30, "CashPay"
        )
        assert enabled is True

    def test_claims_setting_defaults_off(self) -> None:
        with patch("billing_dashboard.handlers.billing_api.build_claims") as mock_build:
            mock_build.return_value = {"claims": []}
            self._handler(
                "/api/claims", "business_line=6f1c2e0a-5b7d-4c1e-9a3b-2d4e6f8a0b1c"
            ).claims()
        query, enabled = mock_build.call_args.args
        assert enabled is False
        assert query.business_line is None

    def test_claims_bad_sort_is_400_without_query(self) -> None:
        with patch("billing_dashboard.handlers.billing_api.build_claims") as mock_build:
            result = self._handler("/api/claims", "sort=note__patient__id").claims()
        assert result[0].status_code == HTTPStatus.BAD_REQUEST
        assert "Unknown sort" in json.loads(result[0].content)["error"]
        mock_build.assert_not_called()

    def test_claims_unknown_queue_is_400(self) -> None:
        from billing_dashboard.data.claims import ClaimsQueryError

        with patch("billing_dashboard.handlers.billing_api.build_claims") as mock_build:
            mock_build.side_effect = ClaimsQueryError("Unknown claim queue 'X'.")
            result = self._handler("/api/claims", "queue=X").claims()
        assert result[0].status_code == HTTPStatus.BAD_REQUEST
        assert json.loads(result[0].content) == {"error": "Unknown claim queue 'X'."}

    def test_csv_response_headers_and_body(self) -> None:
        with patch("billing_dashboard.handlers.billing_api.build_claims_csv") as mock_csv:
            mock_csv.return_value = ('"Claim #"\r\n', True)
            result = self._handler("/api/claims.csv", "sort=balance").claims_csv()
        resp = result[0]
        assert resp.status_code == HTTPStatus.OK
        assert resp.content == b'"Claim #"\r\n'
        assert resp.headers["Content-Type"] == "text/csv; charset=utf-8"
        assert resp.headers["Content-Disposition"].startswith('attachment; filename="claims-')
        assert resp.headers["Cache-Control"] == "no-store"
        assert resp.headers["X-Claims-Truncated"] == "true"
        assert mock_csv.call_args.args[0].sort == "balance"

    def test_csv_bad_params_is_400(self) -> None:
        with patch("billing_dashboard.handlers.billing_api.build_claims_csv") as mock_csv:
            result = self._handler("/api/claims.csv", "window=7").claims_csv()
        assert result[0].status_code == HTTPStatus.BAD_REQUEST
        mock_csv.assert_not_called()
