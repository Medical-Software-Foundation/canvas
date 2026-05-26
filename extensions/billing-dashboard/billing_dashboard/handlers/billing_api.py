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


def _build_inline_html() -> str:
    css = render_to_string("static/css/styles.css") or ""
    html = render_to_string("templates/page.html") or ""
    return html.replace("%%CSS%%", css)


class BillingDashboardAPI(StaffSessionAuthMixin, SimpleAPI):
    PREFIX = ""

    @api.get("/dashboard")
    def dashboard(self) -> list[Response | Effect]:
        log.info("[BillingDashboardAPI] Serving dashboard page")
        return [HTMLResponse(_build_inline_html(), status_code=HTTPStatus.OK)]

    @api.get("/api/metrics")
    def metrics(self) -> list[Response | Effect]:
        tab = self.request.query_params.get("tab", "overview")
        log.info("[BillingDashboardAPI] Fetching metrics for tab: %s", tab)
        if tab == "overview":
            data = build_overview()
        elif tab == "payer":
            data = build_payer()
        elif tab == "trends":
            data = build_trends()
        else:
            data = {"message": "Unknown tab"}
        return [JSONResponse(data, status_code=HTTPStatus.OK)]
