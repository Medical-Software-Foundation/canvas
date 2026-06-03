"""Tests for provider_availability.engine.tz_utils."""

from datetime import UTC, datetime
from unittest.mock import call, patch
from zoneinfo import ZoneInfo

from provider_availability.engine.tz_utils import (
    localize_naive,
    practice_now,
    practice_tz,
    provider_tz,
    to_practice_naive,
    to_utc,
)


TZ_MODULE = "provider_availability.engine.tz_utils"


class TestPracticeTz:
    def test_returns_zoneinfo(self):
        with patch(f"{TZ_MODULE}.get_practice_timezone", return_value="US/Eastern"):
            result = practice_tz()
            assert result == ZoneInfo("US/Eastern")


class TestProviderTz:
    def test_returns_provider_specific_tz(self):
        with patch(f"{TZ_MODULE}.get_provider_timezone", return_value="US/Pacific"):
            result = provider_tz("provider-1")
            assert result == ZoneInfo("US/Pacific")

    def test_falls_back_to_practice_tz(self):
        with patch(f"{TZ_MODULE}.get_provider_timezone", return_value=""), \
             patch(f"{TZ_MODULE}.get_practice_timezone", return_value="US/Eastern"):
            result = provider_tz("provider-1")
            assert result == ZoneInfo("US/Eastern")


class TestPracticeNow:
    def test_returns_aware_datetime(self):
        with patch(f"{TZ_MODULE}.get_practice_timezone", return_value="US/Eastern"):
            result = practice_now()
            assert result.tzinfo is not None


class TestToUtc:
    def test_converts_eastern_to_utc(self):
        eastern = ZoneInfo("US/Eastern")
        dt_eastern = datetime(2026, 3, 10, 9, 0, tzinfo=eastern)
        result = to_utc(dt_eastern)
        assert result.tzinfo == UTC
        # Eastern is UTC-4 in March (EDT)
        assert result.hour == 13

    def test_utc_stays_utc(self):
        dt_utc = datetime(2026, 3, 10, 9, 0, tzinfo=UTC)
        result = to_utc(dt_utc)
        assert result.hour == 9


class TestLocalizeNaive:
    def test_with_explicit_tz(self):
        eastern = ZoneInfo("US/Eastern")
        naive = datetime(2026, 3, 10, 9, 0)
        result = localize_naive(naive, eastern)
        assert result.tzinfo == eastern
        assert result.hour == 9

    def test_with_practice_tz(self):
        with patch(f"{TZ_MODULE}.get_practice_timezone", return_value="US/Pacific"):
            naive = datetime(2026, 3, 10, 9, 0)
            result = localize_naive(naive)
            assert result.tzinfo == ZoneInfo("US/Pacific")


class TestToPracticeNaive:
    def test_aware_to_naive(self):
        with patch(f"{TZ_MODULE}.get_practice_timezone", return_value="US/Eastern"):
            utc_dt = datetime(2026, 3, 10, 13, 0, tzinfo=UTC)
            result = to_practice_naive(utc_dt)
            # UTC 13:00 = EDT 9:00
            assert result.tzinfo is None
            assert result.hour == 9

    def test_naive_passthrough(self):
        naive = datetime(2026, 3, 10, 9, 0)
        result = to_practice_naive(naive)
        assert result is naive
