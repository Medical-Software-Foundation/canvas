"""Tests for billing_dashboard.data.cms_rates — CMS Physician Fee Schedule lookup."""

import pytest

from billing_dashboard.data import cms_rates


class TestCmsRatesTable:
    def test_99214_rate_matches_current_benchmark(self) -> None:
        assert cms_rates.CMS_RATES["99214"] == 128.94

    def test_contains_all_cpt_codes_from_mock_trends(self) -> None:
        expected = {"99214", "99213", "99215", "99203", "99204", "99395"}
        assert expected <= set(cms_rates.CMS_RATES.keys())


class TestGetCmsRate:
    def test_returns_rate_for_known_cpt(self) -> None:
        assert cms_rates.get_cms_rate("99214") == 128.94

    def test_returns_none_for_unknown_cpt(self) -> None:
        assert cms_rates.get_cms_rate("99999") is None


class TestGetCptDescription:
    def test_returns_description_for_known_cpt(self) -> None:
        assert cms_rates.get_cpt_description("99214") == "Office visit, established patient (moderate)"

    def test_returns_none_for_unknown_cpt(self) -> None:
        assert cms_rates.get_cpt_description("99999") is None


class TestPrimaryBenchmark:
    def test_exports_primary_benchmark_constant(self) -> None:
        assert cms_rates.CMS_PRIMARY_BENCHMARK == 128.94
