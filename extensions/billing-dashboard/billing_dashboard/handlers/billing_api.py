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

# Bump this whenever styles.css or main.js change so browsers don't serve
# stale cached copies after a plugin update. The ``__VERSION__`` sentinel in
# templates/page.html is substituted with this value at render time. Done
# this way (rather than via ``{{ }}`` template syntax) so the upload payload
# doesn't trigger SSTI-style WAF rules that flag double-brace patterns.
ASSET_VERSION = "4"


class BillingDashboardAPI(StaffSessionAuthMixin, SimpleAPI):
    PREFIX = ""

    @api.get("/dashboard")
    def dashboard(self) -> list[Response | Effect]:
        log.info("[BillingDashboardAPI] Serving dashboard page")
        # render_to_string raises FileNotFoundError if the template is absent.
        # Let it propagate to the SDK exception handler (→ Sentry, → 500) per
        # the global "errors must reach Sentry" rule. A missing static asset
        # is a packaging defect, not a runtime condition to mask.
        html = render_to_string("templates/page.html").replace("__VERSION__", ASSET_VERSION)
        return [HTMLResponse(html, status_code=HTTPStatus.OK)]

    @api.get("/styles.css")
    def styles_css(self) -> list[Response | Effect]:
        css = render_to_string("static/css/styles.css")
        return [Response(css.encode(), status_code=HTTPStatus.OK, content_type="text/css")]

    @api.get("/main.js")
    def main_js(self) -> list[Response | Effect]:
        js = render_to_string("static/js/main.js")
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
