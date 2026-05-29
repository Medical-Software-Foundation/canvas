"""Tests for billing_dashboard.data.trends — CPT-level Trends tab builder."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import arrow
import pytest

from billing_dashboard.data import trends


@pytest.fixture
def fixed_now() -> arrow.Arrow:
    return arrow.get(2026, 4, 15, 14, 30, 0)


def _cpt_qs(rows: list[dict]) -> MagicMock:
    qs = MagicMock()
    qs.objects.filter.return_value.values.return_value.annotate.return_value.order_by.return_value.__getitem__.return_value = rows
    return qs


class TestCptCodeAggregation:
    @patch("billing_dashboard.data.trends.ChargeDescriptionMaster")
    @patch("billing_dashboard.data.trends.BillingLineItem")
    def test_groups_by_cpt_with_your_avg_charge_and_volume(
        self, mock_bli: MagicMock, mock_cdm: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        mock_bli.objects.filter.return_value.values.return_value.annotate.return_value.order_by.return_value.__getitem__.return_value = [
            {"cpt": "99214", "your_avg_charge": Decimal("131.20"), "volume": 45, "sample_description": None},
            {"cpt": "99213", "your_avg_charge": Decimal("92.50"),  "volume": 22, "sample_description": None},
        ]
        mock_cdm.objects.filter.return_value.order_by.return_value.values_list.return_value = [
            ("99214", "Established patient, moderate complexity"),
            ("99213", "Established patient, low complexity"),
        ]
        result = trends.cpt_codes(now=fixed_now)
        assert result["source"] == "real"
        rows = result["data"]
        assert len(rows) == 2
        assert rows[0]["code"] == "99214"
        # CDM short_name wins over hardcoded description
        assert rows[0]["description"] == "Established patient, moderate complexity"
        assert rows[0]["cms_rate"] == 128.94
        assert rows[0]["your_avg_charge"] == pytest.approx(131.20)

    @patch("billing_dashboard.data.trends.ChargeDescriptionMaster")
    @patch("billing_dashboard.data.trends.BillingLineItem")
    def test_newest_cdm_revision_wins_over_older(
        self, mock_bli: MagicMock, mock_cdm: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        """When a CPT has multiple CDM revisions, the newest short_name wins.

        Regression: the lookup orders by ascending effective_date so dict()'s
        last-write-wins collapse picks the newest row. Reversing to
        ``-effective_date`` would surface the oldest description instead.
        """
        mock_bli.objects.filter.return_value.values.return_value.annotate.return_value.order_by.return_value.__getitem__.return_value = [
            {"cpt": "99214", "your_avg_charge": Decimal("131.20"), "volume": 45, "sample_description": None},
        ]
        # Production sorts ascending so the rightmost tuple is the newest.
        mock_cdm.objects.filter.return_value.order_by.return_value.values_list.return_value = [
            ("99214", "Established visit"),                              # oldest
            ("99214", "Office visit, est. patient"),                     # middle
            ("99214", "Office visit, established patient (moderate)"),   # newest
        ]
        row = trends.cpt_codes(now=fixed_now)["data"][0]
        assert row["description"] == "Office visit, established patient (moderate)"
        mock_cdm.objects.filter.return_value.order_by.assert_called_once_with("cpt_code", "effective_date")

    @patch("billing_dashboard.data.trends.ChargeDescriptionMaster")
    @patch("billing_dashboard.data.trends.BillingLineItem")
    def test_description_fallback_chain(
        self, mock_bli: MagicMock, mock_cdm: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        """CDM empty → BLI sample_description → hardcoded → blank."""
        mock_bli.objects.filter.return_value.values.return_value.annotate.return_value.order_by.return_value.__getitem__.return_value = [
            {"cpt": "90999", "your_avg_charge": Decimal("50.0"), "volume": 5, "sample_description": "Custom procedure"},
        ]
        mock_cdm.objects.filter.return_value.order_by.return_value.values_list.return_value = []
        row = trends.cpt_codes(now=fixed_now)["data"][0]
        assert row["description"] == "Custom procedure"

    @patch("billing_dashboard.data.trends.ChargeDescriptionMaster")
    @patch("billing_dashboard.data.trends.BillingLineItem")
    def test_unknown_cpt_has_empty_description_and_null_cms_rate(
        self, mock_bli: MagicMock, mock_cdm: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        mock_bli.objects.filter.return_value.values.return_value.annotate.return_value.order_by.return_value.__getitem__.return_value = [
            {"cpt": "99999", "your_avg_charge": Decimal("50.0"), "volume": 5, "sample_description": None},
        ]
        mock_cdm.objects.filter.return_value.order_by.return_value.values_list.return_value = []
        row = trends.cpt_codes(now=fixed_now)["data"][0]
        assert row["description"] == ""
        assert row["cms_rate"] is None

    @patch("billing_dashboard.data.trends.BillingLineItem")
    def test_empty_returns_mock(
        self, mock_bli: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        mock_bli.objects.filter.return_value.values.return_value.annotate.return_value.order_by.return_value.__getitem__.return_value = []
        result = trends.cpt_codes(now=fixed_now)
        assert result["source"] == "mock"
        assert len(result["data"]) == 6

    @patch("billing_dashboard.data.trends.BillingLineItem")
    def test_filters_entered_in_error_bli(
        self, mock_bli: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        """Regression: BLI queries must filter out entered_in_error rows or
        retracted line items will inflate CPT averages."""
        mock_bli.objects.filter.return_value.values.return_value.annotate.return_value.order_by.return_value.__getitem__.return_value = []
        trends.cpt_codes(now=fixed_now)
        kwargs = mock_bli.objects.filter.call_args.kwargs
        assert kwargs.get("entered_in_error__isnull") is True


class TestMonthlyAvg:
    @patch("billing_dashboard.data.trends.BillingLineItem")
    def test_monthly_average_shape(
        self, mock_bli: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        mock_bli.objects.filter.return_value.values.return_value.annotate.return_value.order_by.return_value = [
            {"created__year": 2025, "created__month": 4, "avg_charge": Decimal("118.50")},
            {"created__year": 2025, "created__month": 5, "avg_charge": Decimal("121.30")},
        ]
        result = trends.monthly_avg(now=fixed_now)
        assert result["source"] == "real"
        assert result["data"][0]["month"] == "Apr 2025"
        assert result["data"][0]["avg_charge"] == pytest.approx(118.50)

    @patch("billing_dashboard.data.trends.BillingLineItem")
    def test_empty_returns_mock(
        self, mock_bli: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        mock_bli.objects.filter.return_value.values.return_value.annotate.return_value.order_by.return_value = []
        result = trends.monthly_avg(now=fixed_now)
        assert result["source"] == "mock"
        assert len(result["data"]) == 12


class TestBuildTrends:
    @patch("billing_dashboard.data.trends.cpt_codes")
    @patch("billing_dashboard.data.trends.monthly_avg")
    def test_assembles_full_payload(
        self, mock_monthly: MagicMock, mock_cpt: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        mock_cpt.return_value = {"source": "real", "data": []}
        mock_monthly.return_value = {"source": "real", "data": []}
        result = trends.build_trends(now=fixed_now)
        assert result["cms_benchmark"] == 128.94
        assert result["cpt_codes"]["source"] == "real"
        assert result["monthly_avg"]["source"] == "real"
