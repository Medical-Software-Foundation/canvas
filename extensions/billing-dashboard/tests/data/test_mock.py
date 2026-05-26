"""Tests for billing_dashboard.data.mock — mock payload module.

These tests pin the exact field names and sample values so the Phase 1 refactor
does not change the UI contract.
"""

import pytest

from billing_dashboard.data import mock


class TestFinancialOverview:
    def test_summary_keys_present(self) -> None:
        summary = mock.financial_overview()["summary"]
        assert set(summary.keys()) == {
            "last_month_collected",
            "this_month_to_date",
            "next_month_projected",
            "claim_acceptance_rate",
            "last_month_trend_pct",
            "next_month_appt_count",
        }

    def test_summary_values_pinned(self) -> None:
        summary = mock.financial_overview()["summary"]
        assert summary["last_month_collected"] == 42580.00
        assert summary["this_month_to_date"] == 18340.00
        assert summary["claim_acceptance_rate"] == 93.4

    def test_daily_list_has_19_rows(self) -> None:
        assert len(mock.financial_overview()["daily"]) == 19

    def test_monthly_list_has_12_rows(self) -> None:
        assert len(mock.financial_overview()["monthly"]) == 12

    def test_insights_list_has_three_entries(self) -> None:
        entries = mock.financial_overview()["insights"]
        assert len(entries) == 3
        assert {e["severity"] for e in entries} == {"warning", "critical", "info"}


class TestPayerAnalysis:
    def test_payers_list_has_six_entries(self) -> None:
        assert len(mock.payer_analysis()["payers"]) == 6

    def test_medicare_delta_is_zero(self) -> None:
        medicare = next(p for p in mock.payer_analysis()["payers"] if p["name"] == "Medicare")
        assert medicare["cms_delta"] == 0.00


class TestTrends:
    def test_cpt_table_has_six_entries(self) -> None:
        assert len(mock.trends()["cpt_codes"]) == 6

    def test_monthly_avg_has_twelve_entries(self) -> None:
        assert len(mock.trends()["monthly_avg"]) == 12

    def test_cms_benchmark_matches_lookup(self) -> None:
        from billing_dashboard.data.cms_rates import CMS_PRIMARY_BENCHMARK
        assert mock.trends()["cms_benchmark"] == CMS_PRIMARY_BENCHMARK


class TestPurity:
    def test_each_call_returns_a_fresh_dict(self) -> None:
        first = mock.financial_overview()
        second = mock.financial_overview()
        first["summary"]["last_month_collected"] = 0
        assert second["summary"]["last_month_collected"] == 42580.00
