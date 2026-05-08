"""Staff-facing membership directory.

Backs the ``MembershipAdminApp`` Application — when staff open *Memberships*
from the provider menu, the SDK launches a new browser window pointed at
``GET /admin/page``, which renders a single-page table of every membership
on the instance.

Endpoints (require an authenticated staff session):
  GET /admin/page          — HTML directory page (Canvas dark theme)
  GET /admin/memberships   — JSON list backing the table

The table is intentionally read-only. Staff redirect patients to the portal
to manage their own memberships.

Base URL:
  https://<instance>.canvasmedical.com/plugin-io/api/portal_membership/admin
"""
from http import HTTPStatus
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string

from portal_membership.models import Membership
from portal_membership.utils.billing_cycle import cadence_suffix

# Statuses staff care about. ``pending_signup`` is a transient mutex state and
# is always excluded from the directory.
_LISTED_STATUSES = ("active", "cancelled")
_VALID_FILTERS = ("all", "active", "cancelled")


class MembershipAdminAPI(StaffSessionAuthMixin, SimpleAPI):
    """Read-only membership directory for staff."""

    PREFIX = "/admin"

    @api.get("/memberships")
    def get_memberships(self) -> list[Response | Effect]:
        """Return all memberships, joined with patient name + DOB.

        Query params:
          ``status`` — ``all`` (default), ``active``, or ``cancelled``.
        """
        status_filter = (self.request.query_params.get("status") or "all").lower()
        if status_filter not in _VALID_FILTERS:
            return [
                JSONResponse(
                    {"error": f"Unknown status filter: {status_filter}"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        if status_filter == "all":
            qs = Membership.objects.filter(status__in=_LISTED_STATUSES)
        else:
            qs = Membership.objects.filter(status=status_filter)
        qs = qs.select_related("patient").order_by("-created_at")

        rows: list[dict[str, Any]] = []
        for m in qs:
            patient = m.patient
            rows.append(
                {
                    "patient_id": str(patient.id),
                    "patient_name": str(patient) if patient else "(unknown)",
                    "dob": patient.birth_date.isoformat()
                    if patient and patient.birth_date
                    else "",
                    "plan": m.plan_name or m.plan or "",
                    "status": m.status,
                    "next_billing_date": m.next_billing_date.isoformat()
                    if m.next_billing_date
                    else "",
                    "amount_display": _format_amount(m.amount_cents, m.currency, m.cadence),
                    "signed_up_at": m.created_at.date().isoformat() if m.created_at else "",
                }
            )

        return [JSONResponse({"memberships": rows, "total": len(rows)})]

    @api.get("/page")
    def get_page(self) -> list[Response | Effect]:
        """Serve the HTML staff directory page."""
        instance = self.environment.get("CUSTOMER_IDENTIFIER", "")
        chart_base = f"https://{instance}.canvasmedical.com/patient" if instance else "/patient"
        api_base = "/plugin-io/api/portal_membership/admin"
        html = render_to_string(
            "templates/admin_directory.html",
            {"chart_base": chart_base, "api_base": api_base},
        )
        return [HTMLResponse(html, status_code=HTTPStatus.OK)]


def _format_amount(amount_cents: int | None, currency: str | None, cadence: str | None) -> str:
    if not amount_cents:
        return ""
    symbol = "$" if (currency or "usd").lower() == "usd" else ""
    return f"{symbol}{amount_cents / 100:.2f}{cadence_suffix(cadence)}"
