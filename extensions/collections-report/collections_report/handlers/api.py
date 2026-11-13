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
from canvas_sdk.v1.data.claim import Claim, ClaimQueues, InstallmentPlanStatus
from canvas_sdk.v1.data.posting import CoveragePosting
from django.db.models import Q

from logger import log

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))

VALID_METHODS = {"cash", "check", "card", "other"}


def _serialize_collection(pc):
    """Serialize a PaymentCollection to a dict for the frontend."""
    # Get patient name via BulkPatientPosting -> payer (Patient)
    patient_name = ""
    try:
        bulk = pc.bulkpatientposting
    except PaymentCollection.bulkpatientposting.RelatedObjectDoesNotExist:
        bulk = None

    if bulk and bulk.payer:
        patient_name = f"{bulk.payer.first_name} {bulk.payer.last_name}".strip()

    return {
        "id": str(pc.id),
        "date": pc.created.isoformat() if pc.created else None,
        "date_display": pc.created.strftime("%m/%d/%Y %I:%M %p") if pc.created else "",
        "amount": str(pc.total_collected),
        "amount_display": f"${pc.total_collected:,.2f}" if pc.total_collected else "$0.00",
        "method": pc.method or "",
        "method_display": (pc.method or "").capitalize(),
        "patient_name": patient_name or "\u2014",
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


def _balance_claims():
    """Claims that count toward a patient's balance, using Canvas's own rule.

    Mirrors home-app's InvoiceHelper.patient_account_balance (the number shown
    as the patient's balance in Canvas), so the totals here match the chart:
      - exclude trashed claims
      - exclude claims on an installment plan, unless the plan was cancelled
      - exclude negative-balance claims that have coverage but no insurance
        posting yet (negative_claims_without_insurance_transaction)
    Claims with a zero patient balance contribute nothing and are skipped.
    """
    claims = (
        Claim.objects
        .exclude(current_queue__queue_sort_ordering=ClaimQueues.TRASH)
        .filter(
            Q(installment_plan__isnull=True)
            | Q(installment_plan__status=InstallmentPlanStatus.CANCELLED)
        )
        .exclude(patient_balance=0)
        .filter(note__isnull=False)
        .select_related("note", "note__patient")
        .distinct()
    )

    negative_with_coverage = set(
        Claim.objects
        .filter(patient_balance__lt=0, coverages__isnull=False)
        .values_list("id", flat=True)
    )
    with_insurance_posting = set(
        CoveragePosting.objects
        .filter(claim_id__in=negative_with_coverage, entered_in_error__isnull=True)
        .values_list("claim_id", flat=True)
    )
    excluded = negative_with_coverage - with_insurance_posting

    return [c for c in claims if c.id not in excluded]


def _query_balances():
    """Patients who owe money, one row per patient, largest balance first."""
    by_patient = {}
    for claim in _balance_claims():
        patient = claim.note.patient
        if patient is None:
            continue
        row = by_patient.setdefault(patient.id, {
            "patient": patient,
            "balance": Decimal("0.00"),
            "open_claims": 0,
            "oldest_dos": None,
        })
        row["balance"] = row["balance"] + claim.patient_balance
        if claim.patient_balance > 0:
            row["open_claims"] = row["open_claims"] + 1
            dos = claim.note.datetime_of_service
            if dos and (row["oldest_dos"] is None or dos < row["oldest_dos"]):
                row["oldest_dos"] = dos

    rows = []
    for row in by_patient.values():
        if row["balance"] <= 0:
            continue
        patient = row["patient"]
        oldest = row["oldest_dos"]
        rows.append({
            "patient_id": str(patient.id),
            "patient_name": f"{patient.first_name} {patient.last_name}".strip() or "—",
            "balance": str(row["balance"]),
            "balance_display": f"${row['balance']:,.2f}",
            "open_claims": row["open_claims"],
            "oldest_dos": oldest.date().isoformat() if oldest else "",
            "oldest_dos_display": oldest.strftime("%m/%d/%Y") if oldest else "",
        })
    rows.sort(key=lambda r: Decimal(r["balance"]), reverse=True)
    return rows


def _balances_summary(rows):
    """Total owed and patient count across all balance rows."""
    total = sum((Decimal(r["balance"]) for r in rows), Decimal("0.00"))
    return {
        "total": str(total),
        "total_display": f"${total:,.2f}",
        "patients": len(rows),
    }


def _csv_cell(value):
    """Quote a value for safe inclusion in a CSV cell."""
    val = str(value if value is not None else "").replace('"', '""')
    return f'"{val}"'


class CollectionsAPI(StaffSessionAuthMixin, SimpleAPI):
    """Serves the collections report UI and data API."""

    PREFIX = "/collections"

    def _parse_range(self):
        """Parse start_date/end_date/method query params.

        Returns (start_date, end_date, method_filter, error_response).
        If parsing fails, error_response is a JSONResponse and the dates
        are None; otherwise error_response is None.
        """
        today = datetime.now(timezone.utc).date()

        start_str = self.request.query_params.get("start_date", "")
        end_str = self.request.query_params.get("end_date", "")

        try:
            start_date = date.fromisoformat(start_str) if start_str else today
        except ValueError:
            return None, None, None, JSONResponse(
                {"error": "Invalid start_date format. Use YYYY-MM-DD."},
                status_code=HTTPStatus.BAD_REQUEST,
            )

        try:
            end_date = date.fromisoformat(end_str) if end_str else today
        except ValueError:
            return None, None, None, JSONResponse(
                {"error": "Invalid end_date format. Use YYYY-MM-DD."},
                status_code=HTTPStatus.BAD_REQUEST,
            )

        if end_date < start_date:
            end_date = start_date

        method_filter = self.request.query_params.get("method", "").lower()
        if method_filter not in VALID_METHODS:
            method_filter = ""

        return start_date, end_date, method_filter, None

    def _query_collections(self, start_date, end_date, method_filter):
        """Run the PaymentCollection query and return serialized records."""
        qs = (
            PaymentCollection.objects
            .filter(created__date__gte=start_date, created__date__lte=end_date)
            .select_related("bulkpatientposting", "bulkpatientposting__payer")
            .order_by("-created")
        )
        if method_filter:
            qs = qs.filter(method=method_filter)
        return [_serialize_collection(pc) for pc in qs]

    @api.get("/data")
    def get_collections(self) -> list[Response | Effect]:
        """Return payment collections as JSON for a date range.

        Query params:
          - start_date: YYYY-MM-DD (defaults to today)
          - end_date: YYYY-MM-DD (defaults to today)
          - method: optional filter (cash/check/card/other)
        """
        start_date, end_date, method_filter, error = self._parse_range()
        if error:
            return [error]

        collections_data = self._query_collections(start_date, end_date, method_filter)
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

    @api.get("/report.csv")
    def report_csv(self) -> list[Response | Effect]:
        """Serve the collections for a date range as a downloadable CSV file.

        Uses the same query params as /data. Returns the file with a
        Content-Disposition attachment header so the browser downloads it
        natively (works inside the embedded report frame).
        """
        start_date, end_date, method_filter, error = self._parse_range()
        if error:
            return [error]

        collections_data = self._query_collections(start_date, end_date, method_filter)
        log.info(
            f"collections_report CSV export: {len(collections_data)} rows "
            f"{start_date}..{end_date} method='{method_filter}'"
        )

        headers = ["Date/Time", "Patient", "Amount", "Method",
                   "Description", "Check Number", "Deposit Date"]
        lines = [",".join(_csv_cell(h) for h in headers)]
        for item in collections_data:
            row = [
                item["date_display"],
                item["patient_name"],
                item["amount"],
                item["method_display"],
                item["description"],
                item["check_number"],
                item["deposit_date"],
            ]
            lines.append(",".join(_csv_cell(c) for c in row))

        csv_body = "\r\n".join(lines) + "\r\n"

        if start_date == end_date:
            date_label = start_date.isoformat()
        else:
            date_label = f"{start_date.isoformat()}_to_{end_date.isoformat()}"
        filename = f"collections_{date_label}.csv"

        return [Response(
            csv_body.encode(),
            status_code=HTTPStatus.OK,
            content_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )]

    @api.get("/balances")
    def get_balances(self) -> list[Response | Effect]:
        """Return patients with an outstanding balance as JSON.

        Current balances as of now; not date filtered.
        """
        rows = _query_balances()
        return [JSONResponse(
            {
                "balances": rows,
                "summary": _balances_summary(rows),
                "count": len(rows),
            },
            status_code=HTTPStatus.OK,
        )]

    @api.get("/balances.csv")
    def balances_csv(self) -> list[Response | Effect]:
        """Serve patients with an outstanding balance as a downloadable CSV."""
        rows = _query_balances()
        log.info(f"collections_report balances CSV export: {len(rows)} rows")

        headers = ["Patient", "Balance Owed", "Open Claims", "Oldest Date of Service"]
        lines = [",".join(_csv_cell(h) for h in headers)]
        for row in rows:
            lines.append(",".join(_csv_cell(c) for c in [
                row["patient_name"],
                row["balance"],
                row["open_claims"],
                row["oldest_dos_display"],
            ]))
        csv_body = "\r\n".join(lines) + "\r\n"

        filename = f"balances_owed_{datetime.now(timezone.utc).date().isoformat()}.csv"
        return [Response(
            csv_body.encode(),
            status_code=HTTPStatus.OK,
            content_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )]
