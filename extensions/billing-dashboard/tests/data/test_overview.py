"""Tests for billing_dashboard.data.overview — real-data Overview tab builder."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import arrow
import pytest

from billing_dashboard.data import overview


@pytest.fixture
def fixed_now() -> arrow.Arrow:
    return arrow.get(2026, 4, 15, 14, 30, 0)


class TestFiledClaimsQuerySet:
    @patch("billing_dashboard.data.overview.Claim")
    def test_filters_to_filed_or_later_and_modified_range(
        self, mock_claim: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        start = arrow.get(2026, 3, 1, 0, 0, 0)
        end = arrow.get(2026, 4, 1, 0, 0, 0)
        overview.filed_claims_in_range(start, end)
        mock_claim.objects.filter.assert_called_once_with(
            current_queue__queue_sort_ordering__gte=5,
            modified__range=(start.datetime, end.datetime),
        )

    @patch("billing_dashboard.data.overview.Claim")
    def test_excludes_trashed_claims(
        self, mock_claim: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        """Regression: TRASH ordinal (10) is >= FILED (5), so a bare
        ``__gte=FILED`` filter would silently include deleted claims in
        revenue and acceptance-rate aggregates."""
        start, end = arrow.get(2026, 3, 1), arrow.get(2026, 4, 1)
        overview.filed_claims_in_range(start, end)
        mock_claim.objects.filter.return_value.exclude.assert_called_once_with(
            current_queue__queue_sort_ordering=10,
        )


class TestAggregateFiledClaims:
    @patch("billing_dashboard.data.overview.Claim")
    def test_returns_count_and_total(self, mock_claim: MagicMock, fixed_now: arrow.Arrow) -> None:
        # filed_claims_in_range now does Claim.objects.filter().exclude();
        # the aggregate is on the exclude() result.
        mock_claim.objects.filter.return_value.exclude.return_value.aggregate.return_value = {
            "count": 42,
            "total": Decimal("1234.56"),
        }
        start, end = arrow.get(2026, 3, 1), arrow.get(2026, 4, 1)
        result = overview.aggregate_filed_claims(start, end)
        assert result == {"count": 42, "total": Decimal("1234.56")}


class TestLastMonthCollected:
    @patch("billing_dashboard.data.overview.aggregate_filed_claims")
    def test_returns_sum_with_source_real(
        self, mock_agg: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        mock_agg.return_value = {"count": 5, "total": Decimal("3500")}
        result = overview.last_month_collected(now=fixed_now)
        assert result == {"value": 3500.0, "source": "real"}

    @patch("billing_dashboard.data.overview.aggregate_filed_claims")
    def test_zero_count_uses_mock_fallback(
        self, mock_agg: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        mock_agg.return_value = {"count": 0, "total": None}
        result = overview.last_month_collected(now=fixed_now)
        assert result["source"] == "mock"
        assert result["value"] == 42580.00

    @patch("billing_dashboard.data.overview.aggregate_filed_claims")
    def test_claims_with_no_payments_still_real(
        self, mock_agg: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        """Filed claims exist but total_paid is 0 — real source, zero value."""
        mock_agg.return_value = {"count": 10, "total": None}
        result = overview.last_month_collected(now=fixed_now)
        assert result["source"] == "real"
        assert result["value"] == 0.0


class TestThisMonthCollected:
    @patch("billing_dashboard.data.overview.aggregate_filed_claims")
    def test_returns_sum_with_source_real(
        self, mock_agg: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        mock_agg.return_value = {"count": 2, "total": Decimal("500.00")}
        result = overview.this_month_collected(now=fixed_now)
        assert result == {"value": 500.0, "source": "real"}

    @patch("billing_dashboard.data.overview.aggregate_filed_claims")
    def test_zero_count_uses_mock(
        self, mock_agg: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        mock_agg.return_value = {"count": 0, "total": None}
        result = overview.this_month_collected(now=fixed_now)
        assert result["source"] == "mock"


class TestComputeTrendPct:
    def test_positive_growth(self) -> None:
        assert overview.compute_trend_pct(Decimal("110"), Decimal("100")) == pytest.approx(10.0)

    def test_negative_growth(self) -> None:
        assert overview.compute_trend_pct(Decimal("90"), Decimal("100")) == pytest.approx(-10.0)

    def test_zero_prior_returns_none(self) -> None:
        """No baseline means no percentage. Returning 0.0 here would silently
        render as '0.0% from prior month / No change' even when the current
        month had real activity emerging from nothing."""
        assert overview.compute_trend_pct(Decimal("500"), Decimal("0")) is None


class TestLastMonthTrendPct:
    @patch("billing_dashboard.data.overview.aggregate_filed_claims")
    def test_real_branch_computes_pct(
        self, mock_agg: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        # Last month total 200, prior 100 → +100%
        mock_agg.side_effect = [
            {"count": 2, "total": Decimal("200")},
            {"count": 1, "total": Decimal("100")},
        ]
        result = overview.last_month_trend_pct(now=fixed_now)
        assert result["source"] == "real"
        assert result["value"] == pytest.approx(100.0)

    @patch("billing_dashboard.data.overview.aggregate_filed_claims")
    def test_both_zero_falls_back_to_mock(
        self, mock_agg: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        mock_agg.side_effect = [
            {"count": 0, "total": None},
            {"count": 0, "total": None},
        ]
        result = overview.last_month_trend_pct(now=fixed_now)
        assert result["source"] == "mock"

    @patch("billing_dashboard.data.overview.aggregate_filed_claims")
    def test_real_activity_with_zero_prior_marks_no_baseline(
        self, mock_agg: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        """Last month had real collections but the prior month did not.
        Result must be sourced as 'no_baseline' so the JS renders 'No
        prior-month baseline' rather than the misleading 'No change'."""
        mock_agg.side_effect = [
            {"count": 5, "total": Decimal("500")},  # last month
            {"count": 0, "total": None},             # prior month
        ]
        result = overview.last_month_trend_pct(now=fixed_now)
        assert result == {"value": 0.0, "source": "no_baseline"}

    @patch("billing_dashboard.data.overview.arrow")
    @patch("billing_dashboard.data.overview.aggregate_filed_claims")
    def test_defaults_to_utcnow_when_now_omitted(
        self, mock_agg: MagicMock, mock_arrow: MagicMock
    ) -> None:
        sentinel = arrow.get(2026, 4, 15, 0, 0, 0)
        mock_arrow.utcnow.return_value = sentinel
        mock_agg.return_value = {"count": 1, "total": Decimal("100")}
        overview.last_month_trend_pct()
        assert mock_arrow.utcnow.called


class TestClaimAcceptanceRate:
    @patch("billing_dashboard.data.overview.Claim")
    def test_ratio_of_non_rejected_to_filed(
        self, mock_claim: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        mock_claim.objects.filter.return_value.exclude.return_value.aggregate.return_value = {
            "filed_total": 100,
            "rejected": 8,
        }
        result = overview.claim_acceptance_rate(now=fixed_now)
        assert result["source"] == "real"
        assert result["value"] == pytest.approx(92.0)

    @patch("billing_dashboard.data.overview.Claim")
    def test_zero_filed_returns_mock(
        self, mock_claim: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        mock_claim.objects.filter.return_value.exclude.return_value.aggregate.return_value = {
            "filed_total": 0,
            "rejected": 0,
        }
        result = overview.claim_acceptance_rate(now=fixed_now)
        assert result["source"] == "mock"


class TestNextMonthAppointmentCount:
    @patch("billing_dashboard.data.overview.Appointment")
    def test_counts_appointments_in_next_month(
        self, mock_appointment: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        mock_appointment.objects.filter.return_value.count.return_value = 312
        result = overview.next_month_appointment_count(now=fixed_now)
        assert result == {"value": 312, "source": "real"}


class TestNextMonthProjected:
    @patch("billing_dashboard.data.overview.next_month_appointment_count")
    @patch("billing_dashboard.data.overview.aggregate_filed_claims")
    def test_real_projection_is_count_times_avg(
        self, mock_agg: MagicMock, mock_appts: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        # 10 appts × (800/2 avg) = 4000
        mock_appts.return_value = {"value": 10, "source": "real"}
        mock_agg.return_value = {"count": 2, "total": Decimal("800")}
        result = overview.next_month_projected(now=fixed_now)
        assert result["source"] == "real"
        assert result["value"] == pytest.approx(4000.0)

    @patch("billing_dashboard.data.overview.next_month_appointment_count")
    @patch("billing_dashboard.data.overview.aggregate_filed_claims")
    def test_no_filed_claims_falls_back_to_mock(
        self, mock_agg: MagicMock, mock_appts: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        mock_appts.return_value = {"value": 10, "source": "real"}
        mock_agg.return_value = {"count": 0, "total": None}
        result = overview.next_month_projected(now=fixed_now)
        assert result["source"] == "mock"

    @patch("billing_dashboard.data.overview.next_month_appointment_count")
    @patch("billing_dashboard.data.overview.aggregate_filed_claims")
    def test_uses_provided_appt_count_without_querying(
        self, mock_agg: MagicMock, mock_appts: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        mock_agg.return_value = {"count": 4, "total": Decimal("1000")}
        # 20 appts × (1000/4 avg) = 5000; appt count must not trigger a query
        result = overview.next_month_projected(now=fixed_now, precomputed_appt_count=20)
        assert result == {"value": pytest.approx(5000.0), "source": "real"}
        mock_appts.assert_not_called()


class TestDailyCollections:
    @patch("billing_dashboard.data.overview.filed_claims_in_range")
    def test_groups_by_day_with_db_aggregation(
        self, mock_filed: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        import datetime
        mock_filed.return_value.values.return_value.annotate.return_value.order_by.return_value = [
            {"modified__date": datetime.date(2026, 4, 1), "collected": Decimal("200"), "visits": 1},
            {"modified__date": datetime.date(2026, 4, 3), "collected": Decimal("150"), "visits": 2},
        ]
        result = overview.daily_collections(now=fixed_now)
        assert result["source"] == "real"
        rows = result["data"]
        assert len(rows) == 2
        assert rows[0]["date"] == "Apr 1"
        assert rows[0]["visits"] == 1
        assert rows[0]["collected"] == 200.0
        assert rows[1]["date"] == "Apr 3"
        assert rows[1]["visits"] == 2

    @patch("billing_dashboard.data.overview.filed_claims_in_range")
    def test_empty_returns_mock(
        self, mock_filed: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        mock_filed.return_value.values.return_value.annotate.return_value.order_by.return_value = []
        result = overview.daily_collections(now=fixed_now)
        assert result["source"] == "mock"
        assert len(result["data"]) == 19


class TestMonthlyCollections:
    @patch("billing_dashboard.data.overview.filed_claims_in_range")
    def test_groups_by_month_with_db_aggregation(
        self, mock_filed: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        mock_filed.return_value.values.return_value.annotate.return_value.order_by.return_value = [
            {"modified__year": 2026, "modified__month": 3, "collected": Decimal("300")},
            {"modified__year": 2026, "modified__month": 4, "collected": Decimal("500")},
        ]
        result = overview.monthly_collections(now=fixed_now)
        assert result["source"] == "real"
        by_month = {r["month"]: r["collected"] for r in result["data"]}
        assert by_month["Mar"] == 300.0
        assert by_month["Apr"] == 500.0

    @patch("billing_dashboard.data.overview.filed_claims_in_range")
    def test_empty_returns_mock(
        self, mock_filed: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        mock_filed.return_value.values.return_value.annotate.return_value.order_by.return_value = []
        result = overview.monthly_collections(now=fixed_now)
        assert result["source"] == "mock"
        assert len(result["data"]) == 12


class TestBuildOverview:
    @patch("billing_dashboard.data.overview.last_month_collected")
    @patch("billing_dashboard.data.overview.this_month_collected")
    @patch("billing_dashboard.data.overview.next_month_projected")
    @patch("billing_dashboard.data.overview.claim_acceptance_rate")
    @patch("billing_dashboard.data.overview.last_month_trend_pct")
    @patch("billing_dashboard.data.overview.next_month_appointment_count")
    @patch("billing_dashboard.data.overview.daily_collections")
    @patch("billing_dashboard.data.overview.monthly_collections")
    def test_build_overview_assembles_full_payload(
        self,
        mock_monthly: MagicMock,
        mock_daily: MagicMock,
        mock_appts: MagicMock,
        mock_trend: MagicMock,
        mock_acceptance: MagicMock,
        mock_projected: MagicMock,
        mock_this_month: MagicMock,
        mock_last_month: MagicMock,
        fixed_now: arrow.Arrow,
    ) -> None:
        mock_last_month.return_value = {"value": 1.0, "source": "real"}
        mock_this_month.return_value = {"value": 2.0, "source": "real"}
        mock_projected.return_value = {"value": 3.0, "source": "real"}
        mock_acceptance.return_value = {"value": 95.0, "source": "real"}
        mock_trend.return_value = {"value": 5.0, "source": "real"}
        mock_appts.return_value = {"value": 10, "source": "real"}
        mock_daily.return_value = {"source": "real", "data": []}
        mock_monthly.return_value = {"source": "real", "data": []}

        result = overview.build_overview(now=fixed_now)

        assert set(result["summary"].keys()) == {
            "last_month_collected",
            "this_month_collected",
            "next_month_projected",
            "claim_acceptance_rate",
            "last_month_trend_pct",
            "next_month_appt_count",
        }
        assert result["summary"]["last_month_collected"]["value"] == 1.0
        assert result["daily"]["source"] == "real"
        assert result["monthly"]["source"] == "real"
        assert result["insights"]["source"] == "real"
        assert isinstance(result["insights"]["data"], list)
        mock_appts.assert_called_once()
        mock_projected.assert_called_once_with(fixed_now, precomputed_appt_count=10)
