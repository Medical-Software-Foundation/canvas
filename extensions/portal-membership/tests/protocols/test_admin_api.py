"""Unit tests for MembershipAdminAPI staff directory."""
import json
from datetime import date, datetime, timezone
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from portal_membership.protocols.admin_api import (
    MembershipAdminAPI,
    _format_amount,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_handler(
    mock_event: MagicMock,
    method: str = "GET",
    path: str = "/admin/memberships",
    query: dict[str, str] | None = None,
    environment: dict[str, str] | None = None,
) -> MembershipAdminAPI:
    mock_event.context = {
        "method": method,
        "path": path,
        "headers": {},
    }
    handler = MembershipAdminAPI(event=mock_event)
    handler.secrets = {}
    handler.environment = environment or {}
    handler.request = MagicMock()
    handler.request.query_params = query or {}
    return handler


def _patient(
    patient_id: str = "44827549-a55d-46f6-86ed-ac91058a88e6",
    name: str = "Ada Lovelace",
    birth_date: date | None = None,
) -> MagicMock:
    """Build a patient mock with str(patient) → display name."""
    p = MagicMock()
    p.id = patient_id
    p.birth_date = birth_date or date(1815, 12, 10)
    p.__str__ = lambda self: name  # type: ignore[method-assign]
    return p


def _membership(
    patient: MagicMock | None = None,
    plan: str = "basic",
    plan_name: str = "Basic",
    status: str = "active",
    next_billing_date: date | None = None,
    amount_cents: int = 4900,
    currency: str = "usd",
    cadence: str = "monthly",
    created_at: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        patient=patient or _patient(),
        plan=plan,
        plan_name=plan_name,
        status=status,
        next_billing_date=next_billing_date or date(2026, 5, 30),
        amount_cents=amount_cents,
        currency=currency,
        cadence=cadence,
        created_at=created_at or datetime(2026, 4, 30, 17, 0, tzinfo=timezone.utc),
    )


def _stub_membership_query(
    mock_membership: MagicMock,
    rows: list[SimpleNamespace],
) -> None:
    """Wire ``Membership.objects.filter(...).select_related(...).order_by(...)`` to *rows*."""
    qs = MagicMock()
    qs.select_related.return_value.order_by.return_value = rows
    mock_membership.objects.filter.return_value = qs


# ---------------------------------------------------------------------------
# _format_amount
# ---------------------------------------------------------------------------

class TestFormatAmount:
    def test_monthly(self) -> None:
        assert _format_amount(4900, "usd", "monthly") == "$49.00/mo"

    def test_daily(self) -> None:
        assert _format_amount(100, "usd", "daily") == "$1.00/day"

    def test_zero_returns_empty(self) -> None:
        assert _format_amount(0, "usd", "monthly") == ""

    def test_non_usd_no_dollar(self) -> None:
        assert _format_amount(9900, "eur", "annually") == "99.00/yr"


# ---------------------------------------------------------------------------
# GET /admin/memberships
# ---------------------------------------------------------------------------

class TestGetMemberships:
    @patch("portal_membership.protocols.admin_api.Membership")
    def test_default_filter_is_all_listed_statuses(
        self,
        mock_membership: MagicMock,
        mock_event: MagicMock,
    ) -> None:
        _stub_membership_query(mock_membership, [_membership()])

        handler = _make_handler(mock_event)
        results = handler.get_memberships()

        first_filter = mock_membership.objects.filter.call_args
        assert first_filter.kwargs == {"status__in": ("active", "cancelled")}
        body = json.loads(results[0].content)
        assert body["total"] == 1
        assert body["memberships"][0]["patient_name"] == "Ada Lovelace"

    @patch("portal_membership.protocols.admin_api.Membership")
    def test_active_filter(
        self,
        mock_membership: MagicMock,
        mock_event: MagicMock,
    ) -> None:
        _stub_membership_query(mock_membership, [])

        handler = _make_handler(mock_event, query={"status": "active"})
        handler.get_memberships()

        assert mock_membership.objects.filter.call_args.kwargs == {"status": "active"}

    @patch("portal_membership.protocols.admin_api.Membership")
    def test_cancelled_filter(
        self,
        mock_membership: MagicMock,
        mock_event: MagicMock,
    ) -> None:
        _stub_membership_query(mock_membership, [])

        handler = _make_handler(mock_event, query={"status": "cancelled"})
        handler.get_memberships()

        assert mock_membership.objects.filter.call_args.kwargs == {"status": "cancelled"}

    def test_invalid_filter_returns_400(self, mock_event: MagicMock) -> None:
        handler = _make_handler(mock_event, query={"status": "garbage"})
        results = handler.get_memberships()
        assert results[0].status_code == HTTPStatus.BAD_REQUEST

    @patch("portal_membership.protocols.admin_api.Membership")
    def test_row_shape_includes_all_fields(
        self,
        mock_membership: MagicMock,
        mock_event: MagicMock,
    ) -> None:
        _stub_membership_query(mock_membership, [_membership()])

        handler = _make_handler(mock_event)
        body = json.loads(handler.get_memberships()[0].content)

        row = body["memberships"][0]
        assert row["patient_id"] == "44827549-a55d-46f6-86ed-ac91058a88e6"
        assert row["patient_name"] == "Ada Lovelace"
        assert row["dob"] == "1815-12-10"
        assert row["plan"] == "Basic"
        assert row["status"] == "active"
        assert row["next_billing_date"] == "2026-05-30"
        assert row["amount_display"] == "$49.00/mo"
        assert row["signed_up_at"] == "2026-04-30"

    @patch("portal_membership.protocols.admin_api.Membership")
    def test_orders_by_created_at_desc(
        self,
        mock_membership: MagicMock,
        mock_event: MagicMock,
    ) -> None:
        qs = MagicMock()
        qs.select_related.return_value.order_by.return_value = []
        mock_membership.objects.filter.return_value = qs

        handler = _make_handler(mock_event)
        handler.get_memberships()

        order_call = qs.select_related.return_value.order_by.call_args
        assert order_call.args == ("-created_at",)


# ---------------------------------------------------------------------------
# GET /admin/page
# ---------------------------------------------------------------------------

class TestGetPage:
    @patch("portal_membership.protocols.admin_api.render_to_string")
    def test_returns_html_with_chart_base(
        self, mock_render: MagicMock, mock_event: MagicMock
    ) -> None:
        mock_render.return_value = "<html>rendered</html>"
        handler = _make_handler(
            mock_event,
            path="/admin/page",
            environment={"CUSTOMER_IDENTIFIER": "acme-health"},
        )
        results = handler.get_page()

        assert results[0].status_code == HTTPStatus.OK
        template, context = mock_render.call_args.args
        assert template == "templates/admin_directory.html"
        assert context["chart_base"] == "https://acme-health.canvasmedical.com/patient"
        assert context["api_base"] == "/plugin-io/api/portal_membership/admin"

    @patch("portal_membership.protocols.admin_api.render_to_string")
    def test_relative_chart_base_when_no_customer_identifier(
        self, mock_render: MagicMock, mock_event: MagicMock
    ) -> None:
        mock_render.return_value = "<html>rendered</html>"
        handler = _make_handler(mock_event, path="/admin/page")
        handler.get_page()

        _, context = mock_render.call_args.args
        assert context["chart_base"] == "/patient"
