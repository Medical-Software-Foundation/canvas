"""Unit tests for MembershipPortalWidget protocol and helpers."""
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from portal_membership.protocols.portal_widget import (
    MembershipPortalWidget,
    _build_widget_context,
    _format_amount,
)


# ---------------------------------------------------------------------------
# _format_amount
# ---------------------------------------------------------------------------

class TestFormatAmount:
    def test_usd_dollar_symbol(self) -> None:
        assert _format_amount(9900, "usd") == "$99.00/mo"

    def test_usd_uppercase(self) -> None:
        assert _format_amount(4900, "USD") == "$49.00/mo"

    def test_non_usd_no_symbol(self) -> None:
        assert _format_amount(9900, "eur") == "99.00/mo"

    def test_zero_returns_empty(self) -> None:
        assert _format_amount(0, "usd") == ""

    def test_none_currency_defaults_usd(self) -> None:
        assert _format_amount(1000, None) == "$10.00/mo"  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        ("cadence", "suffix"),
        [
            ("daily", "/day"),
            ("weekly", "/wk"),
            ("monthly", "/mo"),
            ("quarterly", "/qtr"),
            ("annually", "/yr"),
            (None, "/mo"),
            ("nonsense", "/mo"),
        ],
    )
    def test_cadence_drives_suffix(self, cadence: str | None, suffix: str) -> None:
        assert _format_amount(100, "usd", cadence) == f"$1.00{suffix}"


# ---------------------------------------------------------------------------
# _build_widget_context — active membership
# ---------------------------------------------------------------------------

class TestBuildWidgetContextActive:
    def test_status_is_active(self, active_record: dict[str, Any]) -> None:
        ctx = _build_widget_context(active_record, "https://example.com/page")
        assert ctx["status"] == "active"

    def test_plan_name_present(self, active_record: dict[str, Any]) -> None:
        ctx = _build_widget_context(active_record, "https://example.com/page")
        assert ctx["plan_name"] == "Gold"

    def test_next_billing_present(self, active_record: dict[str, Any]) -> None:
        ctx = _build_widget_context(active_record, "https://example.com/page")
        assert ctx["next_billing"] == "2026-04-11"

    def test_amount_display_formatted(self, active_record: dict[str, Any]) -> None:
        ctx = _build_widget_context(active_record, "https://example.com/page")
        assert ctx["amount_display"] == "$99.00/mo"

    def test_amount_display_uses_record_cadence(self, active_record: dict[str, Any]) -> None:
        active_record["cadence"] = "daily"
        active_record["amount_cents"] = 100
        ctx = _build_widget_context(active_record, "https://example.com/page")
        assert ctx["amount_display"] == "$1.00/day"

    def test_membership_page_url_preserved(self, active_record: dict[str, Any]) -> None:
        url = "https://example.com/membership/page"
        ctx = _build_widget_context(active_record, url)
        assert ctx["membership_page_url"] == url

    def test_charges_page_url_deep_links_to_tab(self, active_record: dict[str, Any]) -> None:
        url = "https://example.com/membership/page"
        ctx = _build_widget_context(active_record, url)
        assert ctx["charges_page_url"] == f"{url}?tab=charges"


# ---------------------------------------------------------------------------
# _build_widget_context — cancelled membership
# ---------------------------------------------------------------------------

class TestBuildWidgetContextCancelled:
    def test_status_is_cancelled(self, cancelled_record: dict[str, Any]) -> None:
        ctx = _build_widget_context(cancelled_record, "https://example.com/page")
        assert ctx["status"] == "cancelled"

    def test_plan_name_present(self, cancelled_record: dict[str, Any]) -> None:
        ctx = _build_widget_context(cancelled_record, "https://example.com/page")
        assert ctx["plan_name"] == "Gold"

    def test_next_billing_present(self, cancelled_record: dict[str, Any]) -> None:
        ctx = _build_widget_context(cancelled_record, "https://example.com/page")
        assert ctx["next_billing"] == "2026-04-11"


# ---------------------------------------------------------------------------
# _build_widget_context — not enrolled (None record)
# ---------------------------------------------------------------------------

class TestBuildWidgetContextNone:
    def test_status_is_none_when_record_is_none(self) -> None:
        ctx = _build_widget_context(None, "https://example.com/page")
        assert ctx["status"] == "none"

    def test_plan_name_is_empty_when_record_is_none(self) -> None:
        ctx = _build_widget_context(None, "https://example.com/page")
        assert ctx["plan_name"] == ""

    def test_amount_display_is_empty_when_record_is_none(self) -> None:
        ctx = _build_widget_context(None, "https://example.com/page")
        assert ctx["amount_display"] == ""

    def test_next_billing_is_empty_when_record_is_none(self) -> None:
        ctx = _build_widget_context(None, "https://example.com/page")
        assert ctx["next_billing"] == ""

    def test_status_none_field_in_record(self) -> None:
        ctx = _build_widget_context({"status": "none"}, "https://example.com/page")
        assert ctx["status"] == "none"

    def test_url_preserved_when_record_is_none(self) -> None:
        url = "https://test.canvasmedical.com/plugin-io/api/portal_membership/membership/page"
        ctx = _build_widget_context(None, url)
        assert ctx["membership_page_url"] == url


# ---------------------------------------------------------------------------
# MembershipPortalWidget.compute
# ---------------------------------------------------------------------------

def _make_handler(
    patient_id: str = "patient-abc-123",
    customer_identifier: str = "my-instance",
) -> MembershipPortalWidget:
    """Build a MembershipPortalWidget with mocked event and environment.

    Canvas delivers the logged-in patient as ``event.target.id`` for
    PATIENT_PORTAL__WIDGET_CONFIGURATION events; ``event.context`` is empty.
    """
    event = MagicMock()
    event.target = SimpleNamespace(id=patient_id)
    event.context = {}
    handler = MembershipPortalWidget(event=event)
    handler.environment = {"CUSTOMER_IDENTIFIER": customer_identifier}
    return handler


class TestMembershipPortalWidgetCompute:
    @patch("portal_membership.protocols.portal_widget.render_to_string")
    @patch("portal_membership.protocols.portal_widget.get_membership")
    def test_active_member_returns_one_effect(
        self,
        mock_get: MagicMock,
        mock_render: MagicMock,
        active_record: dict[str, Any],
    ) -> None:
        from canvas_sdk.effects import Effect

        mock_get.return_value = active_record
        mock_render.return_value = "<html>active</html>"

        handler = _make_handler()
        effects = handler.compute()

        assert len(effects) == 1
        assert isinstance(effects[0], Effect)
        mock_get.assert_called_once_with("patient-abc-123")

    @patch("portal_membership.protocols.portal_widget.render_to_string")
    @patch("portal_membership.protocols.portal_widget.get_membership")
    def test_cancelled_member_returns_one_effect(
        self,
        mock_get: MagicMock,
        mock_render: MagicMock,
        cancelled_record: dict[str, Any],
    ) -> None:
        from canvas_sdk.effects import Effect

        mock_get.return_value = cancelled_record
        mock_render.return_value = "<html>cancelled</html>"

        handler = _make_handler()
        effects = handler.compute()

        assert len(effects) == 1
        assert isinstance(effects[0], Effect)

    @patch("portal_membership.protocols.portal_widget.render_to_string")
    @patch("portal_membership.protocols.portal_widget.get_membership")
    def test_no_record_returns_one_effect(
        self,
        mock_get: MagicMock,
        mock_render: MagicMock,
    ) -> None:
        """Not-enrolled patients still get the widget (showing 'View Plans' CTA)."""
        from canvas_sdk.effects import Effect

        mock_get.return_value = None
        mock_render.return_value = "<html>not enrolled</html>"

        handler = _make_handler()
        effects = handler.compute()

        assert len(effects) == 1
        assert isinstance(effects[0], Effect)

    @patch("portal_membership.protocols.portal_widget.render_to_string")
    @patch("portal_membership.protocols.portal_widget.get_membership")
    def test_template_called_with_correct_path(
        self,
        mock_get: MagicMock,
        mock_render: MagicMock,
    ) -> None:
        mock_get.return_value = None
        mock_render.return_value = "<html/>"

        handler = _make_handler()
        handler.compute()

        mock_render.assert_called_once()
        template_name = mock_render.call_args[0][0]
        assert template_name == "templates/membership_widget.html"

    @patch("portal_membership.protocols.portal_widget.render_to_string")
    @patch("portal_membership.protocols.portal_widget.get_membership")
    def test_membership_page_url_uses_customer_identifier(
        self,
        mock_get: MagicMock,
        mock_render: MagicMock,
    ) -> None:
        mock_get.return_value = None
        mock_render.return_value = "<html/>"

        handler = _make_handler(customer_identifier="acme-health")
        handler.compute()

        context_arg = mock_render.call_args[0][1]
        assert "acme-health.canvasmedical.com" in context_arg["membership_page_url"]

    @patch("portal_membership.protocols.portal_widget.render_to_string")
    @patch("portal_membership.protocols.portal_widget.get_membership")
    def test_empty_patient_id_uses_empty_string(
        self,
        mock_get: MagicMock,
        mock_render: MagicMock,
    ) -> None:
        """When event.target is missing, should not call get_membership."""
        mock_render.return_value = "<html/>"

        event = MagicMock()
        event.target = None
        event.context = {}
        handler = MembershipPortalWidget(event=event)
        handler.environment = {"CUSTOMER_IDENTIFIER": "test"}

        effects = handler.compute()
        mock_get.assert_not_called()
        assert len(effects) == 1

    @patch("portal_membership.protocols.portal_widget.render_to_string")
    @patch("portal_membership.protocols.portal_widget.get_membership")
    def test_missing_customer_identifier_produces_relative_url(
        self,
        mock_get: MagicMock,
        mock_render: MagicMock,
    ) -> None:
        mock_get.return_value = None
        mock_render.return_value = "<html/>"

        event = MagicMock()
        event.target = SimpleNamespace(id="p1")
        event.context = {}
        handler = MembershipPortalWidget(event=event)
        handler.environment = {}

        handler.compute()
        context_arg = mock_render.call_args[0][1]
        # With no CUSTOMER_IDENTIFIER, api_base is empty so URL starts with /plugin-io
        assert context_arg["membership_page_url"].startswith(
            "/plugin-io/api/portal_membership/membership/page"
        )
