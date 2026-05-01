"""Unit tests for MembershipBanner protocol and helpers in membership_card.py."""
from typing import Any
from unittest.mock import MagicMock, patch


def _set_members(mock_membership_cls: MagicMock, patient_ids: list[str]) -> None:
    """Arrange `Membership.objects.exclude(status='')` to yield patients."""
    from types import SimpleNamespace
    mock_membership_cls.objects.exclude.return_value = [
        SimpleNamespace(patient_id=pid) for pid in patient_ids
    ]


# Backwards-compatible alias used by existing tests.
_set_active = _set_members


import pytest

from portal_membership.protocols.membership_card import (
    BANNER_KEY,
    MembershipBanner,
    _build_banner_effects,
    _build_narrative,
    _format_amount,
)


# ---------------------------------------------------------------------------
# _format_amount
# ---------------------------------------------------------------------------

class TestFormatAmount:
    def test_usd_rounds_two_decimals(self) -> None:
        assert _format_amount(9900, "usd") == "$99.00/mo"

    def test_usd_uppercase_currency(self) -> None:
        assert _format_amount(4900, "USD") == "$49.00/mo"

    def test_non_usd_no_dollar_symbol(self) -> None:
        result = _format_amount(9900, "eur")
        assert result == "99.00/mo"

    def test_none_amount_returns_empty(self) -> None:
        assert _format_amount(None, "usd") == ""

    def test_zero_amount_returns_empty(self) -> None:
        assert _format_amount(0, "usd") == ""

    def test_none_currency_defaults_to_usd_symbol(self) -> None:
        result = _format_amount(1000, None)
        assert result == "$10.00/mo"

    @pytest.mark.parametrize(
        ("cadence", "suffix"),
        [
            ("daily", "/day"),
            ("weekly", "/wk"),
            ("monthly", "/mo"),
            ("quarterly", "/qtr"),
            ("annually", "/yr"),
        ],
    )
    def test_cadence_drives_suffix(self, cadence: str, suffix: str) -> None:
        assert _format_amount(100, "usd", cadence) == f"$1.00{suffix}"


# ---------------------------------------------------------------------------
# _build_narrative — active membership
# ---------------------------------------------------------------------------

class TestBuildNarrativeActive:
    def test_includes_plan_name(self, active_record: dict[str, Any]) -> None:
        narrative = _build_narrative(active_record)
        assert "Gold" in narrative

    def test_includes_amount(self, active_record: dict[str, Any]) -> None:
        narrative = _build_narrative(active_record)
        assert "$99.00/mo" in narrative

    def test_includes_next_billing_date_when_fits(self, active_record: dict[str, Any]) -> None:
        narrative = _build_narrative(active_record)
        assert "2026-04-11" in narrative
        assert "Next:" in narrative

    def test_no_plan_name_still_renders(self) -> None:
        record = {"status": "active", "amount_cents": 4900, "currency": "usd"}
        narrative = _build_narrative(record)
        assert "$49.00/mo" in narrative

    def test_no_amount_still_renders(self) -> None:
        record = {"status": "active", "plan_name": "Basic"}
        narrative = _build_narrative(record)
        assert "Basic" in narrative

    def test_no_plan_no_amount_fallback(self) -> None:
        record = {"status": "active"}
        narrative = _build_narrative(record)
        assert narrative == "Active Membership"

    def test_long_narrative_drops_billing_date(self) -> None:
        """When adding billing date would exceed 90 chars, it is omitted."""
        # plan_name (70) + " — " (3) + "$99.00/mo" (9) = 82 chars base;
        # adding " · Next: 2026-04-11" (19) would reach 101 > 90.
        record = {
            "status": "active",
            "plan_name": "A" * 70,
            "amount_cents": 9900,
            "currency": "usd",
            "next_billing_date": "2026-04-11",
        }
        narrative = _build_narrative(record)
        assert len(narrative) <= 90
        assert "Next:" not in narrative


# ---------------------------------------------------------------------------
# _build_narrative — cancelled membership
# ---------------------------------------------------------------------------

class TestBuildNarrativeCancelled:
    def test_includes_plan_name(self, cancelled_record: dict[str, Any]) -> None:
        narrative = _build_narrative(cancelled_record)
        assert "Gold" in narrative

    def test_includes_effective_date(self, cancelled_record: dict[str, Any]) -> None:
        narrative = _build_narrative(cancelled_record)
        assert "Effective:" in narrative
        assert "2026-04-11" in narrative

    def test_always_includes_cancelled_marker(self, cancelled_record: dict[str, Any]) -> None:
        """Regression: previously dropped the (Cancelled) label when a date was set."""
        narrative = _build_narrative(cancelled_record)
        assert "(Cancelled)" in narrative

    def test_no_billing_date_shows_cancelled_suffix(self) -> None:
        record = {"status": "cancelled", "plan_name": "Gold"}
        narrative = _build_narrative(record)
        assert "Cancelled" in narrative
        assert "Gold" in narrative

    def test_no_plan_name_fallback(self) -> None:
        record = {"status": "cancelled"}
        narrative = _build_narrative(record)
        assert "Cancelled" in narrative


# ---------------------------------------------------------------------------
# _build_narrative — no membership / unknown status
# ---------------------------------------------------------------------------

class TestBuildNarrativeNone:
    def test_returns_empty_for_none_status(self) -> None:
        assert _build_narrative({"status": "none"}) == ""

    def test_returns_empty_for_unknown_status(self) -> None:
        assert _build_narrative({"status": "pending"}) == ""

    def test_returns_empty_for_missing_status_key(self) -> None:
        assert _build_narrative({}) == ""


# ---------------------------------------------------------------------------
# _build_banner_effects
# ---------------------------------------------------------------------------

class TestBuildBannerEffects:
    def test_active_returns_one_effect(self, active_record: dict[str, Any]) -> None:
        effects = _build_banner_effects("patient-1", active_record)
        assert len(effects) == 1

    def test_cancelled_returns_one_effect(self, cancelled_record: dict[str, Any]) -> None:
        effects = _build_banner_effects("patient-1", cancelled_record)
        assert len(effects) == 1

    def test_no_membership_returns_empty(self) -> None:
        effects = _build_banner_effects("patient-1", {"status": "none"})
        assert effects == []

    def test_banner_key_is_constant(self, active_record: dict[str, Any]) -> None:
        assert BANNER_KEY == "membership-status"

    def test_effects_are_effect_instances(self, active_record: dict[str, Any]) -> None:
        from canvas_sdk.effects import Effect

        effects = _build_banner_effects("patient-1", active_record)
        assert all(isinstance(e, Effect) for e in effects)


# ---------------------------------------------------------------------------
# MembershipBanner.compute — PATIENT_UPDATED
# ---------------------------------------------------------------------------

def _make_protocol(
    event_type: int,
    target: str = "patient-abc-123",
) -> MembershipBanner:
    """Build a MembershipBanner handler with a mock event."""
    event = MagicMock()
    event.type = event_type
    event.target.id = target
    return MembershipBanner(event=event)


class TestMembershipBannerPatientUpdated:
    @patch("portal_membership.protocols.membership_card.get_membership")
    def test_active_member_returns_one_effect(
        self,
        mock_get: MagicMock,
        active_record: dict[str, Any],
    ) -> None:
        from canvas_sdk.events import EventType

        mock_get.return_value = active_record
        handler = _make_protocol(EventType.PATIENT_UPDATED, "patient-abc-123")
        effects = handler.compute()
        assert len(effects) == 1
        mock_get.assert_called_once_with("patient-abc-123")

    @patch("portal_membership.protocols.membership_card.get_membership")
    def test_no_record_returns_empty(self, mock_get: MagicMock) -> None:
        from canvas_sdk.events import EventType

        mock_get.return_value = None
        handler = _make_protocol(EventType.PATIENT_UPDATED, "patient-xyz")
        effects = handler.compute()
        assert effects == []

    @patch("portal_membership.protocols.membership_card.get_membership")
    def test_non_member_status_returns_empty(self, mock_get: MagicMock) -> None:
        from canvas_sdk.events import EventType

        mock_get.return_value = {"status": "none"}
        handler = _make_protocol(EventType.PATIENT_UPDATED, "patient-xyz")
        effects = handler.compute()
        assert effects == []

    @patch("portal_membership.protocols.membership_card.get_membership")
    def test_cancelled_member_returns_one_effect(
        self,
        mock_get: MagicMock,
        cancelled_record: dict[str, Any],
    ) -> None:
        from canvas_sdk.events import EventType

        mock_get.return_value = cancelled_record
        handler = _make_protocol(EventType.PATIENT_UPDATED, "patient-abc-123")
        effects = handler.compute()
        assert len(effects) == 1


# ---------------------------------------------------------------------------
# MembershipBanner.compute — PLUGIN_CREATED / PLUGIN_UPDATED
# ---------------------------------------------------------------------------

class TestMembershipBannerPluginEvents:
    @patch("portal_membership.protocols.membership_card.get_membership")
    @patch("portal_membership.protocols.membership_card.Membership")
    def test_plugin_created_emits_one_effect_per_active_patient(
        self,
        mock_membership_cls: MagicMock,
        mock_get: MagicMock,
        active_record: dict[str, Any],
    ) -> None:
        from canvas_sdk.events import EventType

        _set_active(mock_membership_cls, ["p1", "p2", "p3"])
        mock_get.return_value = active_record
        handler = _make_protocol(EventType.PLUGIN_CREATED)
        effects = handler.compute()
        assert len(effects) == 3
        assert mock_get.call_count == 3

    @patch("portal_membership.protocols.membership_card.get_membership")
    @patch("portal_membership.protocols.membership_card.Membership")
    def test_plugin_updated_emits_one_effect_per_active_patient(
        self,
        mock_membership_cls: MagicMock,
        mock_get: MagicMock,
        active_record: dict[str, Any],
    ) -> None:
        from canvas_sdk.events import EventType

        _set_active(mock_membership_cls, ["p1", "p2"])
        mock_get.return_value = active_record
        handler = _make_protocol(EventType.PLUGIN_UPDATED)
        effects = handler.compute()
        assert len(effects) == 2

    @patch("portal_membership.protocols.membership_card.Membership")
    def test_plugin_created_no_active_patients_returns_empty(
        self,
        mock_membership_cls: MagicMock,
    ) -> None:
        from canvas_sdk.events import EventType

        _set_active(mock_membership_cls, [])
        handler = _make_protocol(EventType.PLUGIN_CREATED)
        effects = handler.compute()
        assert effects == []

    @patch("portal_membership.protocols.membership_card.get_membership")
    @patch("portal_membership.protocols.membership_card.Membership")
    def test_plugin_event_skips_patients_with_missing_record(
        self,
        mock_membership_cls: MagicMock,
        mock_get: MagicMock,
    ) -> None:
        """A cache miss for an individual patient should produce no effect for that patient."""
        from canvas_sdk.events import EventType

        _set_active(mock_membership_cls, ["p1", "p2"])
        mock_get.return_value = None  # cache miss for both
        handler = _make_protocol(EventType.PLUGIN_CREATED)
        effects = handler.compute()
        assert effects == []

    @patch("portal_membership.protocols.membership_card.get_membership")
    @patch("portal_membership.protocols.membership_card.Membership")
    def test_plugin_event_skips_non_member_status(
        self,
        mock_membership_cls: MagicMock,
        mock_get: MagicMock,
    ) -> None:
        from canvas_sdk.events import EventType

        _set_active(mock_membership_cls, ["p1"])
        mock_get.return_value = {"status": "none"}
        handler = _make_protocol(EventType.PLUGIN_CREATED)
        effects = handler.compute()
        assert effects == []
