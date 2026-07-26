"""Collections report API handler.

Serves the HTML report UI and a JSON data endpoint for payment collections.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, api
from canvas_sdk.handlers.simple_api.security import StaffSessionAuthMixin
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data import PaymentCollection

from logger import log

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))

VALID_METHODS = {"cash", "check", "card", "other"}


def _serialize_collection(pc):
    """Serialize a PaymentCollection to a dict for the frontend."""
    # Get patient name via BulkPatientPosting -> payer (Patient)
    patient_name = ""
    try:
        bulk = pc.bulkpatientposting
        if bulk and bulk.payer:
            patient_name = f"{bulk.payer.first_name} {bulk.payer.last_name}".strip()
    except Exception:
        # No BulkPatientPosting linked (e.g. insurance-only remittance)
        pass

    return {
        "id": str(pc.id),
        "date": pc.created.isoformat() if pc.created else None,
        "date_display": pc.created.strftime("%m/%d/%Y %I:%M %p") if pc.created else "",
        "amount": str(pc.total_collected),
        "amount_display": f"${pc.total_collected:,.2f}" if pc.total_collected else "$0.00",
        "method": pc.method or "",
        "method_display": (pc.method or "").capitalize(),
        "patient_name": patient_name or "—",
        "description": pc.description or "",
        "check_number": pc.check_number or "",
        "deposit_date": pc.deposit_date.isoformat() if pc.deposit_date else "",
    }


def _compute_summary(collections_data):
    """Compute summary totals from serialized collection records."""
    total = Decimal("0.00")
    by_method = {"cash": Decimal("0.00"), "check": Decimal("0.00"),
                 "card": Decimal("0.00"), "other": Decimal("0.00")}

    for item in collections_data:
        amount = Decimal(item["amount"]) if item["amount"] else Decimal("0.00")
        total += amount
        method = item["method"].lower()
        if method in by_method:
            by_method[method] = by_method[method] + amount
        else:
            by_method["other"] = by_method["other"] + amount

    return {
        "total": str(total),
        "total_display": f"${total:,.2f}",
        "cash": str(by_method["cash"]),
        "cash_display": f"${by_method['cash']:,.2f}",
        "check": str(by_method["check"]),
        "check_display": f"${by_method['check']:,.2f}",
        "card": str(by_method["card"]),
        "card_display": f"${by_method['card']:,.2f}",
        "other": str(by_method["other"]),
        "other_display": f"${by_method['other']:,.2f}",
    }


class CollectionsAPI(StaffSessionAuthMixin, SimpleAPI):
    """Serves the collections report UI and data API."""

    PREFIX = "/collections"

    @api.get("/data")
    def get_collections(self) -> list[Response | Effect]:
        """Return payment collections as JSON for a date range.

        Query params:
          - start_date: YYYY-MM-DD (defaults to today)
          - end_date: YYYY-MM-DD (defaults to today)
          - method: optional filter (cash/check/card/other)
        """
        today = datetime.now(timezone.utc).date()

        start_str = self.request.query_params.get("start_date", "")
        end_str = self.request.query_params.get("end_date", "")

        try:
            start_date = date.fromisoformat(start_str) if start_str else today
        except ValueError:
            return [JSONResponse(
                {"error": "Invalid start_date format. Use YYYY-MM-DD."},
                status_code=HTTPStatus.BAD_REQUEST,
            )]

        try:
            end_date = date.fromisoformat(end_str) if end_str else today
        except ValueError:
            return [JSONResponse(
                {"error": "Invalid end_date format. Use YYYY-MM-DD."},
                status_code=HTTPStatus.BAD_REQUEST,
            )]

        if end_date < start_date:
            end_date = start_date

        qs = (
            PaymentCollection.objects
            .filter(created__date__gte=start_date, created__date__lte=end_date)
            .select_related("bulkpatientposting", "bulkpatientposting__payer")
            .order_by("-created")
        )

        method_filter = self.request.query_params.get("method", "").lower()
        if method_filter and method_filter in VALID_METHODS:
            qs = qs.filter(method=method_filter)

        collections_data = [_serialize_collection(pc) for pc in qs]
        summary = _compute_summary(collections_data)

        return [JSONResponse(
            {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "collections": collections_data,
                "summary": summary,
                "count": len(collections_data),
            },
            status_code=HTTPStatus.OK,
        )]

    @api.get("/report")
    def report_html(self) -> list[Response | Effect]:
        """Serve the HTML report page."""
        return [HTMLResponse(
            render_to_string("templates/report.html", {"cache_bust": _CACHE_BUST}),
            status_code=HTTPStatus.OK,
        )]

    @api.get("/report.css")
    def report_css(self) -> list[Response | Effect]:
        """Serve the report stylesheet."""
        return [Response(
            render_to_string("templates/report.css").encode(),
            status_code=HTTPStatus.OK,
            content_type="text/css",
        )]

    @api.get("/report.js")
    def report_js(self) -> list[Response | Effect]:
        """Serve the report JavaScript."""
        return [Response(
            render_to_string("templates/report.js").encode(),
            status_code=HTTPStatus.OK,
            content_type="text/javascript",
        )]
