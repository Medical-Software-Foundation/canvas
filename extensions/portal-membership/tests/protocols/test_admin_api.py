"""Unit tests for MembershipAdminAPI staff directory."""
import json
from datetime import date, datetime, timezone
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from portal_membership.protocols.admin_api import (
    MembershipAdminAPI,
    _build_patient_map,
    _format_amount,
    _patient_name,
    _with_hyphens,
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


def _membership(
    patient_id: str = "44827549a55d46f686edac91058a88e6",
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
        patient_id=patient_id,
        plan=plan,
        plan_name=plan_name,
        status=status,
        next_billing_date=next_billing_date or date(2026, 5, 30),
        amount_cents=amount_cents,
        currency=currency,
        cadence=cadence,
        created_at=created_at or datetime(2026, 4, 30, 17, 0, tzinfo=timezone.utc),
    )


def _patient(
    patient_id: str = "44827549-a55d-46f6-86ed-ac91058a88e6",
    first_name: str = "Ada",
    last_name: str = "Lovelace",
    birth_date: date | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=patient_id,
        first_name=first_name,
        last_name=last_name,
        birth_date=birth_date or date(1815, 12, 10),
    )


# ---------------------------------------------------------------------------
# _format_amount / _patient_name / _with_hyphens
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


class TestPatientName:
    def test_full_name(self) -> None:
        assert _patient_name(_patient()) == "Ada Lovelace"

    def test_unknown_when_none(self) -> None:
        assert _patient_name(None) == "(unknown)"

    def test_unknown_when_blank(self) -> None:
        p = SimpleNamespace(first_name="", last_name="", birth_date=None)
        assert _patient_name(p) == "(unknown)"


class TestWithHyphens:
    def test_inserts_hyphens(self) -> None:
        assert (
            _with_hyphens("44827549a55d46f686edac91058a88e6")
            == "44827549-a55d-46f6-86ed-ac91058a88e6"
        )

    def test_passes_through_non_32_char(self) -> None:
        assert _with_hyphens("short") == "short"


# ---------------------------------------------------------------------------
# _build_patient_map
# ---------------------------------------------------------------------------

class TestBuildPatientMap:
    @patch("portal_membership.protocols.admin_api.Patient")
    def test_keys_by_bare_id(self, mock_patient: MagicMock) -> None:
        # First call: Patient.objects.filter(id__in=bare_ids)
        mock_patient.objects.filter.return_value = [_patient()]
        m = _build_patient_map(["44827549a55d46f686edac91058a88e6"])
        assert "44827549a55d46f686edac91058a88e6" in m
        assert m["44827549a55d46f686edac91058a88e6"].first_name == "Ada"

    @patch("portal_membership.protocols.admin_api.Patient")
    def test_empty_input(self, mock_patient: MagicMock) -> None:
        assert _build_patient_map([]) == {}
        mock_patient.objects.filter.assert_not_called()

    @patch("portal_membership.protocols.admin_api.Patient")
    def test_swallows_db_errors(self, mock_patient: MagicMock) -> None:
        mock_patient.objects.filter.side_effect = Exception("namespace not provisioned")
        # Both attempts fail; should not raise.
        assert _build_patient_map(["44827549a55d46f686edac91058a88e6"]) == {}


# ---------------------------------------------------------------------------
# GET /admin/memberships
# ---------------------------------------------------------------------------

class TestGetMemberships:
    @patch("portal_membership.protocols.admin_api._build_patient_map")
    @patch("portal_membership.protocols.admin_api.Membership")
    def test_default_filter_is_all_listed_statuses(
        self,
        mock_membership: MagicMock,
        mock_map: MagicMock,
        mock_event: MagicMock,
    ) -> None:
        mock_membership.objects.filter.return_value.order_by.return_value = [_membership()]
        mock_map.return_value = {"44827549a55d46f686edac91058a88e6": _patient()}

        handler = _make_handler(mock_event)
        results = handler.get_memberships()

        # Initial filter call should target the listed statuses.
        first_filter = mock_membership.objects.filter.call_args
        assert first_filter.kwargs == {"status__in": ("active", "cancelled")}
        body = json.loads(results[0].content)
        assert body["total"] == 1
        assert body["memberships"][0]["patient_name"] == "Ada Lovelace"

    @patch("portal_membership.protocols.admin_api._build_patient_map")
    @patch("portal_membership.protocols.admin_api.Membership")
    def test_active_filter(
        self,
        mock_membership: MagicMock,
        mock_map: MagicMock,
        mock_event: MagicMock,
    ) -> None:
        mock_membership.objects.filter.return_value.order_by.return_value = []
        mock_map.return_value = {}

        handler = _make_handler(mock_event, query={"status": "active"})
        handler.get_memberships()

        assert mock_membership.objects.filter.call_args.kwargs == {"status": "active"}

    @patch("portal_membership.protocols.admin_api._build_patient_map")
    @patch("portal_membership.protocols.admin_api.Membership")
    def test_cancelled_filter(
        self,
        mock_membership: MagicMock,
        mock_map: MagicMock,
        mock_event: MagicMock,
    ) -> None:
        mock_membership.objects.filter.return_value.order_by.return_value = []
        mock_map.return_value = {}

        handler = _make_handler(mock_event, query={"status": "cancelled"})
        handler.get_memberships()

        assert mock_membership.objects.filter.call_args.kwargs == {"status": "cancelled"}

    def test_invalid_filter_returns_400(self, mock_event: MagicMock) -> None:
        handler = _make_handler(mock_event, query={"status": "garbage"})
        results = handler.get_memberships()
        assert results[0].status_code == HTTPStatus.BAD_REQUEST

    @patch("portal_membership.protocols.admin_api._build_patient_map")
    @patch("portal_membership.protocols.admin_api.Membership")
    def test_row_shape_includes_all_fields(
        self,
        mock_membership: MagicMock,
        mock_map: MagicMock,
        mock_event: MagicMock,
    ) -> None:
        mock_membership.objects.filter.return_value.order_by.return_value = [_membership()]
        mock_map.return_value = {"44827549a55d46f686edac91058a88e6": _patient()}

        handler = _make_handler(mock_event)
        body = json.loads(handler.get_memberships()[0].content)

        row = body["memberships"][0]
        assert row["patient_id"] == "44827549a55d46f686edac91058a88e6"
        assert row["patient_name"] == "Ada Lovelace"
        assert row["dob"] == "1815-12-10"
        assert row["plan"] == "Basic"
        assert row["status"] == "active"
        assert row["next_billing_date"] == "2026-05-30"
        assert row["amount_display"] == "$49.00/mo"
        assert row["signed_up_at"] == "2026-04-30"

    @patch("portal_membership.protocols.admin_api._build_patient_map")
    @patch("portal_membership.protocols.admin_api.Membership")
    def test_unknown_patient_renders_unknown(
        self,
        mock_membership: MagicMock,
        mock_map: MagicMock,
        mock_event: MagicMock,
    ) -> None:
        mock_membership.objects.filter.return_value.order_by.return_value = [_membership()]
        mock_map.return_value = {}  # patient lookup miss

        handler = _make_handler(mock_event)
        body = json.loads(handler.get_memberships()[0].content)

        assert body["memberships"][0]["patient_name"] == "(unknown)"
        assert body["memberships"][0]["dob"] == ""

    @patch("portal_membership.protocols.admin_api._build_patient_map")
    @patch("portal_membership.protocols.admin_api.Membership")
    def test_orders_by_created_at_desc(
        self,
        mock_membership: MagicMock,
        mock_map: MagicMock,
        mock_event: MagicMock,
    ) -> None:
        mock_membership.objects.filter.return_value.order_by.return_value = []
        mock_map.return_value = {}

        handler = _make_handler(mock_event)
        handler.get_memberships()

        order_call = mock_membership.objects.filter.return_value.order_by.call_args
        assert order_call.args == ("-created_at",)


# ---------------------------------------------------------------------------
# GET /admin/page
# ---------------------------------------------------------------------------

class TestGetPage:
    def test_returns_html_with_chart_base(self, mock_event: MagicMock) -> None:
        handler = _make_handler(
            mock_event,
            path="/admin/page",
            environment={"CUSTOMER_IDENTIFIER": "acme-health"},
        )
        results = handler.get_page()

        assert results[0].status_code == HTTPStatus.OK
        html = (
            results[0].content.decode()
            if isinstance(results[0].content, bytes)
            else results[0].content
        )
        assert "Memberships" in html
        assert "acme-health.canvasmedical.com/patient" in html
        # Table headers
        for header in ("Patient", "DOB", "Plan", "Status", "Next billing", "Amount", "Signed up"):
            assert header in html

    def test_relative_chart_base_when_no_customer_identifier(self, mock_event: MagicMock) -> None:
        handler = _make_handler(mock_event, path="/admin/page")
        results = handler.get_page()
        html = (
            results[0].content.decode()
            if isinstance(results[0].content, bytes)
            else results[0].content
        )
        # Falls back to a relative /patient base when CUSTOMER_IDENTIFIER is absent.
        assert '"/patient"' in html
