"""Billing Dashboard SimpleAPI handler — serves UI and JSON metrics."""

from __future__ import annotations

from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string

from billing_dashboard.data.overview import build_overview
from billing_dashboard.data.payer import build_payer
from billing_dashboard.data.trends import build_trends
from logger import log


class BillingDashboardAPI(StaffSessionAuthMixin, SimpleAPI):
    PREFIX = ""

    @api.get("/dashboard")
    def dashboard(self) -> list[Response | Effect]:
        log.info("[BillingDashboardAPI] Serving dashboard page")
        html = render_to_string("templates/page.html") or ""
        return [HTMLResponse(html, status_code=HTTPStatus.OK)]

    @api.get("/styles.css")
    def styles_css(self) -> list[Response | Effect]:
        css = render_to_string("static/css/styles.css") or ""
        return [Response(css.encode(), status_code=HTTPStatus.OK, content_type="text/css")]

    @api.get("/main.js")
    def main_js(self) -> list[Response | Effect]:
        js = render_to_string("static/js/main.js") or ""
        return [Response(js.encode(), status_code=HTTPStatus.OK, content_type="text/javascript")]

    @api.get("/api/metrics")
    def metrics(self) -> list[Response | Effect]:
        tab = self.request.query_params.get("tab", "overview")
        log.info("[BillingDashboardAPI] Fetching metrics for tab: %s", tab)
        if tab == "overview":
            return [JSONResponse(build_overview(), status_code=HTTPStatus.OK)]
        if tab == "payer":
            return [JSONResponse(build_payer(), status_code=HTTPStatus.OK)]
        if tab == "trends":
            return [JSONResponse(build_trends(), status_code=HTTPStatus.OK)]
        log.warning("[BillingDashboardAPI] Unknown tab: %s", tab)
        return [JSONResponse({"error": "Unknown tab"}, status_code=HTTPStatus.BAD_REQUEST)]
