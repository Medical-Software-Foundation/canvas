"""Tests for chart_subscription_auth.ChartSubscriptionAuth."""
from types import SimpleNamespace
from unittest.mock import patch

from provider_clinical_summary_companion.handlers.chart_subscription_auth import (
    ChartSubscriptionAuth,
)


def _make(websocket_user: dict | None) -> ChartSubscriptionAuth:
    handler = ChartSubscriptionAuth.__new__(ChartSubscriptionAuth)
    # websocket is a cached_property; set directly.
    handler.__dict__["websocket"] = SimpleNamespace(logged_in_user=websocket_user)
    return handler


class TestAuthenticate:
    def test_staff_user_passes(self) -> None:
        assert _make({"id": "staff-uuid", "type": "Staff"}).authenticate() is True

    def test_patient_user_rejected(self) -> None:
        assert _make({"id": "pat-uuid", "type": "Patient"}).authenticate() is False

    def test_anonymous_rejected(self) -> None:
        assert _make(None).authenticate() is False
