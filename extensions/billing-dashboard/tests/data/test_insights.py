"""Tests for billing_dashboard.data.insights — rule-based Overview insights."""

import pytest

from billing_dashboard.data import insights


def _summary(**overrides: float) -> dict:
    """Build a summary dict for insight tests. Pass ``key=value`` to override
    a value; source stays ``"real"`` for all entries."""
    base = {
        "last_month_collected":  {"value": 10_000.00, "source": "real"},
        "this_month_collected":  {"value":  5_000.00, "source": "real"},
        "next_month_projected":  {"value":  7_000.00, "source": "real"},
        "last_month_trend_pct":  {"value":      0.0, "source": "real"},
        "next_month_appt_count": {"value":      100, "source": "real"},
        "claim_acceptance_rate": {"value":     95.0, "source": "real"},
    }
    for key, value in overrides.items():
        if key in base:
            base[key] = {"value": value, "source": "real"}
    return base


class TestEmptyCase:
    def test_steady_metrics_produce_no_insights(self) -> None:
        result = insights.compute_insights(_summary())
        assert result == []


class TestRevenueTrendRules:
    def test_revenue_up_fires_at_or_above_ten_pct(self) -> None:
        out = insights.compute_insights(_summary(last_month_trend_pct=10.0))
        assert any(i["title"] == "Revenue trending upward" for i in out)
        assert all(i["severity"] == "info" for i in out if i["title"] == "Revenue trending upward")

    def test_revenue_up_does_not_fire_below_ten_pct(self) -> None:
        out = insights.compute_insights(_summary(last_month_trend_pct=9.9))
        assert not any(i["title"] == "Revenue trending upward" for i in out)

    def test_revenue_down_fires_at_or_below_minus_ten_pct(self) -> None:
        out = insights.compute_insights(_summary(last_month_trend_pct=-10.0))
        assert any(i["title"] == "Revenue declining" for i in out)
        assert all(i["severity"] == "warning" for i in out if i["title"] == "Revenue declining")

    def test_revenue_down_does_not_fire_above_minus_ten_pct(self) -> None:
        out = insights.compute_insights(_summary(last_month_trend_pct=-9.9))
        assert not any(i["title"] == "Revenue declining" for i in out)


class TestAcceptanceRule:
    def test_fires_when_below_ninety(self) -> None:
        out = insights.compute_insights(_summary(claim_acceptance_rate=89.9))
        assert any(i["title"] == "Claim acceptance rate below target" for i in out)
        assert any(i["severity"] == "critical" for i in out if i["title"] == "Claim acceptance rate below target")

    def test_does_not_fire_at_or_above_ninety(self) -> None:
        out = insights.compute_insights(_summary(claim_acceptance_rate=90.0))
        assert not any(i["title"] == "Claim acceptance rate below target" for i in out)

    def test_does_not_fire_when_key_absent(self) -> None:
        summary = _summary()
        del summary["claim_acceptance_rate"]
        out = insights.compute_insights(summary)
        assert not any(i["title"] == "Claim acceptance rate below target" for i in out)


class TestNoUpcomingAppointmentsRule:
    def test_fires_when_count_zero(self) -> None:
        out = insights.compute_insights(_summary(next_month_appt_count=0))
        assert any(i["title"] == "No appointments scheduled next month" for i in out)

    def test_does_not_fire_when_count_positive(self) -> None:
        out = insights.compute_insights(_summary(next_month_appt_count=1))
        assert not any(i["title"] == "No appointments scheduled next month" for i in out)


class TestProjectionConfidenceRule:
    def test_fires_when_projection_more_than_twice_this_month(self) -> None:
        out = insights.compute_insights(_summary(this_month_collected=5_000.00, next_month_projected=10_001.00))
        assert any(i["title"] == "Projected next month is an estimate" for i in out)

    def test_does_not_fire_when_within_two_x(self) -> None:
        out = insights.compute_insights(_summary(this_month_collected=5_000.00, next_month_projected=10_000.00))
        assert not any(i["title"] == "Projected next month is an estimate" for i in out)

    def test_does_not_fire_when_this_month_is_zero(self) -> None:
        out = insights.compute_insights(_summary(this_month_collected=0.0, next_month_projected=10_000.00))
        assert not any(i["title"] == "Projected next month is an estimate" for i in out)


class TestMultipleRules:
    def test_rules_compose(self) -> None:
        out = insights.compute_insights(_summary(
            last_month_trend_pct=-12.0,
            claim_acceptance_rate=80.0,
            next_month_appt_count=0,
        ))
        titles = {i["title"] for i in out}
        assert "Revenue declining" in titles
        assert "Claim acceptance rate below target" in titles
        assert "No appointments scheduled next month" in titles


class TestShape:
    def test_each_insight_has_required_fields(self) -> None:
        out = insights.compute_insights(_summary(last_month_trend_pct=15.0))
        for entry in out:
            assert "severity" in entry
            assert "title" in entry
            assert "description" in entry
            assert "tag" in entry
