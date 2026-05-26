"""Tests for billing_dashboard.data.payer — per-payer Payer tab builder."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import arrow
import pytest

from billing_dashboard.data import payer


@pytest.fixture
def fixed_now() -> arrow.Arrow:
    return arrow.get(2026, 4, 15, 14, 30, 0)


def _set_payer_rows(mock_claim: MagicMock, rows: list[dict]) -> None:
    """Helper to wire up the Claim.objects.filter().exclude().values().annotate() chain."""
    mock_claim.objects.filter.return_value.exclude.return_value.values.return_value.annotate.return_value = rows


class TestPayerAggregation:
    @patch("billing_dashboard.data.payer.Claim")
    def test_returns_per_payer_rows_sorted_by_collected(
        self, mock_claim: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        _set_payer_rows(mock_claim, [
            {"coverages__payer_name": "Aetna",  "collected": Decimal("300"), "total_claims": 10, "rejected_claims": 2},
            {"coverages__payer_name": "CIGNA",  "collected": Decimal("500"), "total_claims": 20, "rejected_claims": 0},
        ])
        result = payer.build_payer(now=fixed_now)
        assert result["payers"]["source"] == "real"
        data = result["payers"]["data"]
        assert data[0]["name"] == "CIGNA"  # higher collected first
        assert data[0]["collected"] == 500.0
        assert data[0]["acceptance_rate"] == 100.0
        assert data[1]["name"] == "Aetna"
        assert data[1]["acceptance_rate"] == 80.0  # (10-2)/10 * 100

    @patch("billing_dashboard.data.payer.Claim")
    def test_cms_delta_is_null_in_v1(
        self, mock_claim: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        _set_payer_rows(mock_claim, [
            {"coverages__payer_name": "Aetna", "collected": Decimal("100"), "total_claims": 1, "rejected_claims": 0},
        ])
        row = payer.build_payer(now=fixed_now)["payers"]["data"][0]
        assert row["cms_delta"] is None

    @patch("billing_dashboard.data.payer.Claim")
    def test_handles_zero_collected_with_real_claims(
        self, mock_claim: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        """Real claims with no postings yet — collected is 0, source still real."""
        _set_payer_rows(mock_claim, [
            {"coverages__payer_name": "Aetna", "collected": None, "total_claims": 5, "rejected_claims": 1},
        ])
        row = payer.build_payer(now=fixed_now)["payers"]["data"][0]
        assert row["collected"] == 0.0
        assert row["acceptance_rate"] == 80.0

    @patch("billing_dashboard.data.payer.Claim")
    def test_blank_payer_name_skipped(
        self, mock_claim: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        _set_payer_rows(mock_claim, [
            {"coverages__payer_name": "", "collected": Decimal("999"), "total_claims": 3, "rejected_claims": 0},
        ])
        result = payer.build_payer(now=fixed_now)
        assert result["payers"]["source"] == "mock"

    @patch("billing_dashboard.data.payer.Claim")
    def test_empty_queryset_returns_mock(
        self, mock_claim: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        _set_payer_rows(mock_claim, [])
        result = payer.build_payer(now=fixed_now)
        assert result["payers"]["source"] == "mock"
        assert len(result["payers"]["data"]) == 6
