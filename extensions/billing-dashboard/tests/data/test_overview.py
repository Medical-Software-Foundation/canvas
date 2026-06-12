"""Tests for billing_dashboard.data.overview — real-data Overview tab builder."""

import inspect
from decimal import Decimal
from unittest.mock import MagicMock, patch

import arrow
import pytest
from django.db.models import Q

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
    def test_zero_count_returns_real_zero(
        self, mock_agg: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        """No filed claims → honest $0 with source=real, not a mock fallback."""
        mock_agg.return_value = {"count": 0, "total": None}
        result = overview.last_month_collected(now=fixed_now)
        assert result == {"value": 0.0, "source": "real"}

    @patch("billing_dashboard.data.overview.aggregate_filed_claims")
    def test_claims_with_no_payments_still_real(
        self, mock_agg: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        """Filed claims exist but total_paid is 0 — real source, zero value."""
        mock_agg.return_value = {"count": 10, "total": None}
        result = overview.last_month_collected(now=fixed_now)
        assert result == {"value": 0.0, "source": "real"}


class TestThisMonthCollected:
    @patch("billing_dashboard.data.overview.aggregate_filed_claims")
    def test_returns_sum_with_source_real(
        self, mock_agg: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        mock_agg.return_value = {"count": 2, "total": Decimal("500.00")}
        result = overview.this_month_collected(now=fixed_now)
        assert result == {"value": 500.0, "source": "real"}

    @patch("billing_dashboard.data.overview.aggregate_filed_claims")
    def test_zero_count_returns_real_zero(
        self, mock_agg: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        mock_agg.return_value = {"count": 0, "total": None}
        result = overview.this_month_collected(now=fixed_now)
        assert result == {"value": 0.0, "source": "real"}


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
    def test_both_zero_returns_no_baseline(
        self, mock_agg: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        """Both months at zero collected → no percentage to compute.
        JS renders this as '— No prior-month baseline'."""
        mock_agg.side_effect = [
            {"count": 0, "total": None},
            {"count": 0, "total": None},
        ]
        result = overview.last_month_trend_pct(now=fixed_now)
        assert result == {"value": None, "source": "no_baseline"}

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
        assert result == {"value": None, "source": "no_baseline"}

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
    def test_zero_filed_returns_no_baseline(
        self, mock_claim: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        """No filed claims → no rate to compute. 0% would falsely suggest 'all
        rejected'; 100% would falsely suggest 'all accepted'. Use no_baseline
        so the JS renders '— No claims to rate' instead."""
        mock_claim.objects.filter.return_value.exclude.return_value.aggregate.return_value = {
            "filed_total": 0,
            "rejected": 0,
        }
        result = overview.claim_acceptance_rate(now=fixed_now)
        assert result == {"value": None, "source": "no_baseline"}


class TestNextMonthAppointmentCount:
    @patch("billing_dashboard.data.overview.Appointment")
    def test_counts_appointments_in_next_month(
        self, mock_appointment: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        mock_appointment.objects.filter.return_value.exclude.return_value.count.return_value = 312
        result = overview.next_month_appointment_count(now=fixed_now)
        assert result == {"value": 312, "source": "real"}

    @patch("billing_dashboard.data.overview.Appointment")
    def test_excludes_cancelled_and_noshowed(
        self, mock_appointment: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        """Regression: cancelled and no-showed appointments stay in the table
        with their original start_time and would otherwise be counted as
        future billable visits, inflating Next Month Projected."""
        from canvas_sdk.v1.data.appointment import AppointmentProgressStatus
        mock_appointment.objects.filter.return_value.exclude.return_value.count.return_value = 0
        overview.next_month_appointment_count(now=fixed_now)
        excluded_statuses = mock_appointment.objects.filter.return_value.exclude.call_args.kwargs["status__in"]
        assert AppointmentProgressStatus.CANCELLED in excluded_statuses
        assert AppointmentProgressStatus.NOSHOWED in excluded_statuses


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
    def test_no_filed_claims_returns_real_zero(
        self, mock_agg: MagicMock, mock_appts: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        """No claim history → no avg to multiply by. Return $0 (real)."""
        mock_appts.return_value = {"value": 10, "source": "real"}
        mock_agg.return_value = {"count": 0, "total": None}
        result = overview.next_month_projected(now=fixed_now)
        assert result == {"value": 0.0, "source": "real"}

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
    def test_empty_returns_real_empty_list(
        self, mock_filed: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        """No claim activity → empty real data. JS renders 'No data in this
        window.' over the chart canvas."""
        mock_filed.return_value.values.return_value.annotate.return_value.order_by.return_value = []
        result = overview.daily_collections(now=fixed_now)
        assert result == {"source": "real", "data": []}


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
    def test_empty_returns_real_empty_list(
        self, mock_filed: MagicMock, fixed_now: arrow.Arrow
    ) -> None:
        mock_filed.return_value.values.return_value.annotate.return_value.order_by.return_value = []
        result = overview.monthly_collections(now=fixed_now)
        assert result == {"source": "real", "data": []}


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


class TestCollectedSumFilterShape:
    """Regression tests that lock in the canonical posting-level retraction filter.

    Background: an earlier commit (``bd9913e``) added a second filter clause
    on ``postings__newlineitempayments__entered_in_error`` to catch payment-
    level retractions under non-voided postings. That filter 500s with a
    Django FieldError at query construction because the field is not declared
    on ``AbstractLineItemTransaction`` (the parent of ``NewLineItemPayment``).
    Per Canvas engineering, a payment is voided by voiding its parent
    posting — there is no per-payment retraction concept in the SDK data
    model. The posting-level filter is the canonical pattern, mirroring
    ``BulkPatientPosting.total_posted_amount`` and ``BasePosting.paid_amount``.

    Full writeup: memory/canvas-sdk-newlineitempayment-no-entered-in-error.md.
    """

    def test_filter_is_single_clause_posting_level(self) -> None:
        """``_COLLECTED_SUM.filter`` must be exactly ``Q(postings__entered_in_error__isnull=True)``.

        If this assertion fails because a second clause has been added, read
        the SDK memory FIRST — the second clause cannot be expressed against
        ``NewLineItemPayment`` because the field isn't on the model.
        """
        filter_q = overview._COLLECTED_SUM.filter
        assert filter_q == Q(postings__entered_in_error__isnull=True)
        assert filter_q.children == [("postings__entered_in_error__isnull", True)]

    def test_filter_does_not_traverse_newlineitempayments(self) -> None:
        """No filter clause may reference the ``newlineitempayments`` reverse-relation path.

        Django raises ``FieldError: Unsupported lookup 'entered_in_error' for
        ManyToOneRel or join on the field not permitted`` at query
        construction the moment such a clause appears, even before any rows
        are touched. This regression catches the re-introduction before
        deploy-time fallout.
        """
        filter_q = overview._COLLECTED_SUM.filter
        forbidden_substring = "newlineitempayments__entered_in_error"
        for lookup, _value in filter_q.children:
            assert forbidden_substring not in lookup, (
                f"_COLLECTED_SUM.filter contains {lookup!r}, which references a field "
                "that does not exist on NewLineItemPayment. See memory/"
                "canvas-sdk-newlineitempayment-no-entered-in-error.md."
            )

    def test_source_does_not_contain_forbidden_lookup(self) -> None:
        """Defense-in-depth: the literal forbidden substring must not appear anywhere in ``data/overview.py``.

        Catches a future Sum that inlines the bad filter outside of the
        module-level ``_COLLECTED_SUM`` constant, or a code comment that
        suggests doing so. Comments that *document the failure mode* are
        allowed because they reference the lookup path on different lines —
        but they don't form the contiguous filter expression
        ``postings__newlineitempayments__entered_in_error``.
        """
        src = inspect.getsource(overview)
        assert "postings__newlineitempayments__entered_in_error" not in src, (
            "data/overview.py contains the forbidden lookup. See memory/"
            "canvas-sdk-newlineitempayment-no-entered-in-error.md."
        )


class TestNewLineItemPaymentSDKInvariant:
    """Invariant: the SDK does NOT expose ``entered_in_error`` on the line-item-transaction hierarchy.

    The day this test starts failing is the day the canonical pattern can be
    augmented with a payment-level filter to also catch payment-row
    retractions under non-voided postings. Until then, the assertion is the
    enforcing source of truth: the plugin's filter shape is constrained by
    the SDK, not by reviewer preference.
    """

    def test_newlineitempayment_has_no_entered_in_error_field(self) -> None:
        from canvas_sdk.v1.data import NewLineItemPayment
        field_names = {f.name for f in NewLineItemPayment._meta.get_fields()}
        assert "entered_in_error" not in field_names, (
            "SDK now exposes `entered_in_error` on NewLineItemPayment! "
            "The posting-level-only filter in `_COLLECTED_SUM` and "
            "`payer.build_payer` can be augmented with a payment-level "
            "clause to catch retracted payment rows under non-voided "
            "postings. Update both modules and refresh memory/"
            "canvas-sdk-newlineitempayment-no-entered-in-error.md."
        )

    def test_posting_does_have_entered_in_error_field(self) -> None:
        """Positive companion: confirms the posting-level field IS available, justifying the canonical filter."""
        from canvas_sdk.v1.data.posting import BasePosting
        field_names = {f.name for f in BasePosting._meta.get_fields()}
        assert "entered_in_error" in field_names, (
            "BasePosting no longer exposes entered_in_error! The canonical "
            "retraction filter `postings__entered_in_error__isnull=True` "
            "will fail. Plugin needs an alternative retraction-detection "
            "path."
        )
