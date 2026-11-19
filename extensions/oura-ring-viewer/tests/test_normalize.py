"""Tests for the pure Oura-to-payload normalization layer."""

import datetime as dt
from typing import Any

import pytest

from oura_ring_viewer.services.normalize import (
    NormalizedDay,
    normalize_activity,
    normalize_readiness,
    normalize_sleep,
    normalize_spo2,
)
from oura_ring_viewer.services.settings import (
    FAMILY_ACTIVITY,
    FAMILY_READINESS,
    FAMILY_SLEEP,
    FAMILY_SPO2,
)

D1 = dt.date(2026, 10, 30)
D2 = dt.date(2026, 10, 31)


def _period(day: dt.date, kind: str = "long_sleep", **fields: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "day": day.isoformat(),
        "type": kind,
        "total_sleep_duration": 25_200,
        "efficiency": 88,
        "average_hrv": 42,
        "lowest_heart_rate": 51,
        "average_heart_rate": 56.375,
    }
    base.update(fields)
    return base


def _only(rows: list[NormalizedDay]) -> NormalizedDay:
    assert len(rows) == 1, rows
    return rows[0]


class TestSleep:
    def test_merges_daily_score_with_main_period(self) -> None:
        row = _only(normalize_sleep([{"day": "2026-10-30", "score": 81}], [_period(D1)]))
        assert row == NormalizedDay(
            day=D1,
            family=FAMILY_SLEEP,
            payload={
                "score": 81,
                "total_sleep_seconds": 25_200,
                "efficiency": 88,
                "average_hrv_ms": 42,
                "lowest_heart_rate_bpm": 51,
                "average_heart_rate_bpm": 56.4,
            },
        )

    def test_overnight_sleep_beats_a_longer_nap(self) -> None:
        """A long_sleep is the night's sleep even if a nap ran longer."""
        night = _period(D1, "long_sleep", total_sleep_duration=21_600, average_hrv=40)
        nap = _period(D1, "late_nap", total_sleep_duration=30_000, average_hrv=99)
        row = _only(normalize_sleep([], [nap, night]))
        assert row.payload["average_hrv_ms"] == 40

    def test_longest_period_wins_without_a_long_sleep(self) -> None:
        short = _period(D1, "sleep", total_sleep_duration=3_600, average_hrv=30)
        long = _period(D1, "sleep", total_sleep_duration=7_200, average_hrv=35)
        row = _only(normalize_sleep([], [short, long]))
        assert row.payload["average_hrv_ms"] == 35

    @pytest.mark.parametrize("kind", ["deleted", "rest", "", None])
    def test_non_sleep_periods_are_ignored(self, kind: str | None) -> None:
        assert normalize_sleep([], [_period(D1, kind)]) == []  # type: ignore[arg-type]

    def test_score_without_a_period_still_produces_a_row(self) -> None:
        row = _only(normalize_sleep([{"day": "2026-10-30", "score": 70}], []))
        assert row.payload["score"] == 70
        assert row.payload["total_sleep_seconds"] is None

    def test_period_without_a_score_still_produces_a_row(self) -> None:
        row = _only(normalize_sleep([], [_period(D1)]))
        assert row.payload["score"] is None
        assert row.payload["lowest_heart_rate_bpm"] == 51

    def test_zero_placeholders_become_gaps_not_readings(self) -> None:
        period = _period(
            D1,
            total_sleep_duration=0,
            efficiency=0,
            average_hrv=0,
            lowest_heart_rate=0,
            average_heart_rate=0,
        )
        assert normalize_sleep([{"day": "2026-10-30", "score": 0}], [period]) == []

    def test_days_come_back_in_order(self) -> None:
        rows = normalize_sleep([], [_period(D2), _period(D1)])
        assert [row.day for row in rows] == [D1, D2]


class TestReadiness:
    def test_score_and_negative_temperature_deviation(self) -> None:
        row = _only(
            normalize_readiness(
                [{"day": "2026-10-30", "score": 77, "temperature_deviation": -0.234}]
            )
        )
        assert row.family == FAMILY_READINESS
        assert row.payload == {"score": 77, "temperature_deviation_c": -0.23}

    def test_zero_temperature_deviation_is_a_real_value(self) -> None:
        row = _only(normalize_readiness([{"day": "2026-10-30", "temperature_deviation": 0}]))
        assert row.payload["temperature_deviation_c"] == 0.0


class TestActivity:
    def test_zero_steps_on_a_sedentary_day_are_kept(self) -> None:
        row = _only(
            normalize_activity([{"day": "2026-10-30", "steps": 0, "active_calories": 0}])
        )
        assert row.family == FAMILY_ACTIVITY
        assert row.payload == {"score": None, "steps": 0, "active_calories": 0}


class TestSpo2:
    def test_nested_average_is_unwrapped(self) -> None:
        row = _only(
            normalize_spo2(
                [
                    {
                        "day": "2026-10-30",
                        "spo2_percentage": {"average": 96.54},
                        "breathing_disturbance_index": 3,
                    }
                ]
            )
        )
        assert row.family == FAMILY_SPO2
        assert row.payload == {"average_pct": 96.5, "breathing_disturbance_index": 3}

    @pytest.mark.parametrize("spo2", [None, {}, {"average": 0}, {"average": None}, "96", 96])
    def test_missing_or_placeholder_average_is_a_gap(self, spo2: Any) -> None:
        row = _only(
            normalize_spo2(
                [{"day": "2026-10-30", "spo2_percentage": spo2, "breathing_disturbance_index": 2}]
            )
        )
        assert row.payload["average_pct"] is None


class TestDefensiveParsing:
    @pytest.mark.parametrize(
        "score", [True, False, "80", 150, -1, float("nan"), float("inf"), None]
    )
    def test_invalid_scores_are_rejected(self, score: Any) -> None:
        assert normalize_readiness([{"day": "2026-10-30", "score": score}]) == []

    @pytest.mark.parametrize("hr", [0, 251, 400, -5])
    def test_implausible_heart_rate_is_rejected(self, hr: int) -> None:
        row = _only(normalize_sleep([], [_period(D1, lowest_heart_rate=hr)]))
        assert row.payload["lowest_heart_rate_bpm"] is None

    @pytest.mark.parametrize(
        "record",
        [None, "text", 42, [], {}, {"day": None}, {"day": "not-a-date"}, {"day": "2026-13-45"}],
    )
    def test_malformed_records_are_skipped(self, record: Any) -> None:
        assert normalize_readiness([record, {"day": "2026-10-30", "score": 60}]) == [
            NormalizedDay(D1, FAMILY_READINESS, {"score": 60, "temperature_deviation_c": None})
        ]

    def test_later_valid_record_for_a_day_wins(self) -> None:
        rows = normalize_readiness(
            [{"day": "2026-10-30", "score": 60}, {"day": "2026-10-30", "score": 65}]
        )
        assert _only(rows).payload["score"] == 65

    def test_later_empty_record_does_not_erase_an_earlier_reading(self) -> None:
        rows = normalize_readiness(
            [{"day": "2026-10-30", "score": 60}, {"day": "2026-10-30", "score": None}]
        )
        assert _only(rows).payload["score"] == 60
