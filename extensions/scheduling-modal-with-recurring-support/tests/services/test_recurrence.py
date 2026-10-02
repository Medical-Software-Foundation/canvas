from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from scheduling_modal_with_recurring_support.services.recurrence import (
    MAX_OCCURRENCES,
    RecurrenceEndCount,
    RecurrenceEndUntil,
    RecurrenceInterval,
    RecurrenceRule,
    RecurrenceUnit,
    RecurrenceValidationError,
    Weekday,
    from_legacy_cadence,
    iter_candidate_first_dates,
    parse_recurrence,
    project_dates,
)


FIXED_TODAY = date(2026, 5, 1)

FIXTURE_PATH = (
    Path(__file__).resolve().parents[1] / "fixtures" / "recurrence_fixtures.json"
)


@pytest.fixture(autouse=True)
def _freeze_today():
    with patch(
        "scheduling_modal_with_recurring_support.services.recurrence._today",
        return_value=FIXED_TODAY,
    ):
        yield


# ---------------------------------------------------------------------------
# parse_recurrence happy paths
# ---------------------------------------------------------------------------


def test_parse_recurrence_minimal_count_rule() -> None:
    rule = parse_recurrence({
        "interval": {"value": 1, "unit": "week"},
        "end": {"kind": "count", "count": 4},
    })

    assert rule == RecurrenceRule(
        interval=RecurrenceInterval(value=1, unit=RecurrenceUnit.WEEK),
        end=RecurrenceEndCount(count=4),
    )


def test_parse_recurrence_until_rule_in_future() -> None:
    rule = parse_recurrence({
        "interval": {"value": 1, "unit": "day"},
        "end": {"kind": "until", "until": "2026-09-01"},
    })

    assert isinstance(rule.end, RecurrenceEndUntil)
    assert rule.end.until == date(2026, 9, 1)


def test_parse_recurrence_until_equal_to_today_is_allowed() -> None:
    rule = parse_recurrence({
        "interval": {"value": 1, "unit": "day"},
        "end": {"kind": "until", "until": FIXED_TODAY.isoformat()},
    })

    assert rule.end == RecurrenceEndUntil(until=FIXED_TODAY)


def test_parse_recurrence_weekdays_normalised_to_calendar_order() -> None:
    rule = parse_recurrence({
        "interval": {"value": 2, "unit": "week"},
        "weekdays": ["WE", "MO"],
        "end": {"kind": "count", "count": 6},
    })

    assert rule.weekdays == (Weekday.MO, Weekday.WE)


def test_parse_recurrence_empty_weekdays_dropped_to_empty_tuple() -> None:
    rule = parse_recurrence({
        "interval": {"value": 1, "unit": "week"},
        "weekdays": [],
        "end": {"kind": "count", "count": 4},
    })

    assert rule.weekdays == ()


def test_parse_recurrence_omitted_weekdays_default_to_empty_tuple() -> None:
    rule = parse_recurrence({
        "interval": {"value": 1, "unit": "week"},
        "end": {"kind": "count", "count": 4},
    })

    assert rule.weekdays == ()


def test_parse_recurrence_exclusions_deduped_and_sorted() -> None:
    rule = parse_recurrence({
        "interval": {"value": 1, "unit": "week"},
        "end": {"kind": "count", "count": 6},
        "exclusions": ["2026-07-04", "2026-05-25", "2026-07-04"],
    })

    assert rule.exclusions == (date(2026, 5, 25), date(2026, 7, 4))


def test_parse_recurrence_omitted_exclusions_default_to_empty_tuple() -> None:
    rule = parse_recurrence({
        "interval": {"value": 1, "unit": "day"},
        "end": {"kind": "count", "count": 1},
    })

    assert rule.exclusions == ()


def test_parsed_rule_is_hashable() -> None:
    rule = parse_recurrence({
        "interval": {"value": 1, "unit": "week"},
        "weekdays": ["MO", "WE"],
        "end": {"kind": "count", "count": 4},
        "exclusions": ["2026-07-04"],
    })

    assert hash(rule) == hash(rule)


# ---------------------------------------------------------------------------
# parse_recurrence validation errors
# ---------------------------------------------------------------------------


def test_parse_recurrence_rejects_non_object_payload() -> None:
    with pytest.raises(RecurrenceValidationError, match="object"):
        parse_recurrence("not a dict")  # type: ignore[arg-type]


def test_parse_recurrence_rejects_missing_interval() -> None:
    with pytest.raises(RecurrenceValidationError, match="interval"):
        parse_recurrence({"end": {"kind": "count", "count": 1}})


def test_parse_recurrence_rejects_zero_interval_value() -> None:
    with pytest.raises(RecurrenceValidationError, match="interval.value"):
        parse_recurrence({
            "interval": {"value": 0, "unit": "week"},
            "end": {"kind": "count", "count": 4},
        })


def test_parse_recurrence_rejects_negative_interval_value() -> None:
    with pytest.raises(RecurrenceValidationError, match="interval.value"):
        parse_recurrence({
            "interval": {"value": -1, "unit": "week"},
            "end": {"kind": "count", "count": 4},
        })


def test_parse_recurrence_rejects_non_integer_interval_value() -> None:
    with pytest.raises(RecurrenceValidationError, match="interval.value"):
        parse_recurrence({
            "interval": {"value": 1.5, "unit": "week"},
            "end": {"kind": "count", "count": 4},
        })


def test_parse_recurrence_rejects_bool_interval_value() -> None:
    with pytest.raises(RecurrenceValidationError, match="interval.value"):
        parse_recurrence({
            "interval": {"value": True, "unit": "week"},
            "end": {"kind": "count", "count": 4},
        })


def test_parse_recurrence_rejects_unknown_interval_unit() -> None:
    with pytest.raises(RecurrenceValidationError, match="interval.unit"):
        parse_recurrence({
            "interval": {"value": 1, "unit": "fortnight"},
            "end": {"kind": "count", "count": 4},
        })


def test_parse_recurrence_rejects_weekdays_with_non_week_unit() -> None:
    with pytest.raises(RecurrenceValidationError, match="weekdays"):
        parse_recurrence({
            "interval": {"value": 1, "unit": "day"},
            "weekdays": ["MO"],
            "end": {"kind": "count", "count": 4},
        })


def test_parse_recurrence_rejects_unknown_weekday_code() -> None:
    with pytest.raises(RecurrenceValidationError, match="weekdays"):
        parse_recurrence({
            "interval": {"value": 1, "unit": "week"},
            "weekdays": ["MO", "XX"],
            "end": {"kind": "count", "count": 4},
        })


def test_parse_recurrence_rejects_duplicate_weekday() -> None:
    with pytest.raises(RecurrenceValidationError, match="duplicate"):
        parse_recurrence({
            "interval": {"value": 1, "unit": "week"},
            "weekdays": ["MO", "MO"],
            "end": {"kind": "count", "count": 4},
        })


def test_parse_recurrence_rejects_unknown_end_kind() -> None:
    with pytest.raises(RecurrenceValidationError, match="end.kind"):
        parse_recurrence({
            "interval": {"value": 1, "unit": "week"},
            "end": {"kind": "forever"},
        })


def test_parse_recurrence_rejects_zero_end_count() -> None:
    with pytest.raises(RecurrenceValidationError, match="end.count"):
        parse_recurrence({
            "interval": {"value": 1, "unit": "week"},
            "end": {"kind": "count", "count": 0},
        })


def test_parse_recurrence_rejects_end_count_above_max() -> None:
    with pytest.raises(RecurrenceValidationError, match="end.count"):
        parse_recurrence({
            "interval": {"value": 1, "unit": "week"},
            "end": {"kind": "count", "count": MAX_OCCURRENCES + 1},
        })


def test_parse_recurrence_accepts_end_count_at_max() -> None:
    rule = parse_recurrence({
        "interval": {"value": 1, "unit": "week"},
        "end": {"kind": "count", "count": MAX_OCCURRENCES},
    })

    assert rule.end == RecurrenceEndCount(count=MAX_OCCURRENCES)


def test_parse_recurrence_rejects_until_in_the_past() -> None:
    yesterday = (FIXED_TODAY - timedelta(days=1)).isoformat()

    with pytest.raises(RecurrenceValidationError, match="past"):
        parse_recurrence({
            "interval": {"value": 1, "unit": "day"},
            "end": {"kind": "until", "until": yesterday},
        })


def test_parse_recurrence_rejects_malformed_until() -> None:
    with pytest.raises(RecurrenceValidationError, match="end.until"):
        parse_recurrence({
            "interval": {"value": 1, "unit": "day"},
            "end": {"kind": "until", "until": "not-a-date"},
        })


def test_parse_recurrence_rejects_non_array_exclusions() -> None:
    with pytest.raises(RecurrenceValidationError, match="exclusions"):
        parse_recurrence({
            "interval": {"value": 1, "unit": "week"},
            "end": {"kind": "count", "count": 4},
            "exclusions": "2026-07-04",
        })


def test_parse_recurrence_rejects_malformed_exclusion_entry() -> None:
    with pytest.raises(RecurrenceValidationError, match="exclusions"):
        parse_recurrence({
            "interval": {"value": 1, "unit": "week"},
            "end": {"kind": "count", "count": 4},
            "exclusions": ["nope"],
        })


# ---------------------------------------------------------------------------
# from_legacy_cadence
# ---------------------------------------------------------------------------


def test_from_legacy_cadence_single_drops_occurrences_to_one() -> None:
    rule = from_legacy_cadence("single", 12)

    assert rule == RecurrenceRule(
        interval=RecurrenceInterval(value=1, unit=RecurrenceUnit.DAY),
        end=RecurrenceEndCount(count=1),
    )


def test_from_legacy_cadence_weekly() -> None:
    rule = from_legacy_cadence("weekly", 12)

    assert rule == RecurrenceRule(
        interval=RecurrenceInterval(value=1, unit=RecurrenceUnit.WEEK),
        end=RecurrenceEndCount(count=12),
    )


def test_from_legacy_cadence_biweekly() -> None:
    rule = from_legacy_cadence("biweekly", 8)

    assert rule == RecurrenceRule(
        interval=RecurrenceInterval(value=2, unit=RecurrenceUnit.WEEK),
        end=RecurrenceEndCount(count=8),
    )


def test_from_legacy_cadence_monthly() -> None:
    rule = from_legacy_cadence("monthly", 6)

    assert rule == RecurrenceRule(
        interval=RecurrenceInterval(value=1, unit=RecurrenceUnit.MONTH),
        end=RecurrenceEndCount(count=6),
    )


def test_from_legacy_cadence_caps_at_max_occurrences() -> None:
    rule = from_legacy_cadence("weekly", MAX_OCCURRENCES + 100)

    assert rule.end == RecurrenceEndCount(count=MAX_OCCURRENCES)


def test_from_legacy_cadence_rejects_unknown_string() -> None:
    with pytest.raises(RecurrenceValidationError, match="unknown cadence"):
        from_legacy_cadence("yearly", 4)


def test_from_legacy_cadence_rejects_zero_occurrences() -> None:
    with pytest.raises(RecurrenceValidationError, match="occurrences"):
        from_legacy_cadence("weekly", 0)


def test_from_legacy_cadence_rejects_negative_occurrences() -> None:
    with pytest.raises(RecurrenceValidationError, match="occurrences"):
        from_legacy_cadence("weekly", -1)


def test_from_legacy_cadence_rejects_bool_occurrences() -> None:
    with pytest.raises(RecurrenceValidationError, match="occurrences"):
        from_legacy_cadence("weekly", True)  # type: ignore[arg-type]


def test_from_legacy_cadence_rejects_non_string_cadence() -> None:
    with pytest.raises(RecurrenceValidationError, match="cadence"):
        from_legacy_cadence(123, 4)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# project_dates fixture-driven tests
# ---------------------------------------------------------------------------


def _load_fixture_cases() -> list[dict]:
    return json.loads(FIXTURE_PATH.read_text())


@pytest.mark.parametrize(
    "case",
    _load_fixture_cases(),
    ids=lambda c: c["name"],
)
def test_project_dates_matches_fixture(case: dict) -> None:
    rule = parse_recurrence(case["rule"])
    start = date.fromisoformat(case["start"])
    expected = [date.fromisoformat(d) for d in case["expected"]]

    assert project_dates(start, rule) == expected


def test_project_dates_returns_empty_when_first_candidate_past_until() -> None:
    rule = RecurrenceRule(
        interval=RecurrenceInterval(value=1, unit=RecurrenceUnit.DAY),
        end=RecurrenceEndUntil(until=date(2026, 5, 3)),
    )

    assert project_dates(date(2026, 5, 4), rule) == []


def test_project_dates_count_capped_at_max_when_count_exceeds() -> None:
    rule = RecurrenceRule(
        interval=RecurrenceInterval(value=1, unit=RecurrenceUnit.DAY),
        end=RecurrenceEndCount(count=MAX_OCCURRENCES),
    )

    result = project_dates(date(2026, 5, 4), rule)

    assert len(result) == MAX_OCCURRENCES
    assert result[0] == date(2026, 5, 4)
    assert result[-1] == date(2026, 5, 4) + timedelta(days=MAX_OCCURRENCES - 1)


def test_project_dates_weekdays_ignored_for_unit_day() -> None:
    rule = RecurrenceRule(
        interval=RecurrenceInterval(value=1, unit=RecurrenceUnit.DAY),
        end=RecurrenceEndCount(count=3),
        weekdays=(Weekday.MO,),
    )

    assert project_dates(date(2026, 5, 5), rule) == [
        date(2026, 5, 5),
        date(2026, 5, 6),
        date(2026, 5, 7),
    ]


def test_project_dates_weekdays_skip_in_first_week_when_before_start() -> None:
    rule = RecurrenceRule(
        interval=RecurrenceInterval(value=1, unit=RecurrenceUnit.WEEK),
        end=RecurrenceEndCount(count=2),
        weekdays=(Weekday.MO,),
    )

    assert project_dates(date(2026, 5, 6), rule) == [
        date(2026, 5, 11),
        date(2026, 5, 18),
    ]


# ---------------------------------------------------------------------------
# iter_candidate_first_dates
# ---------------------------------------------------------------------------


def test_iter_candidate_first_dates_unit_day_yields_every_date() -> None:
    rule = RecurrenceRule(
        interval=RecurrenceInterval(value=1, unit=RecurrenceUnit.DAY),
        end=RecurrenceEndCount(count=5),
    )

    result = list(
        iter_candidate_first_dates(rule, date(2026, 5, 4), date(2026, 5, 8))
    )

    assert result == [
        date(2026, 5, 4),
        date(2026, 5, 5),
        date(2026, 5, 6),
        date(2026, 5, 7),
        date(2026, 5, 8),
    ]


def test_iter_candidate_first_dates_unit_week_no_weekdays_yields_every_date() -> None:
    rule = RecurrenceRule(
        interval=RecurrenceInterval(value=1, unit=RecurrenceUnit.WEEK),
        end=RecurrenceEndCount(count=4),
    )

    result = list(
        iter_candidate_first_dates(rule, date(2026, 5, 4), date(2026, 5, 6))
    )

    assert result == [date(2026, 5, 4), date(2026, 5, 5), date(2026, 5, 6)]


def test_iter_candidate_first_dates_unit_week_with_weekdays_filters() -> None:
    """Mon May 4 is a Monday. Wed May 6 is a Wednesday. The rule has MO,WE so
    only those two weekdays in the window are candidates.
    """
    rule = RecurrenceRule(
        interval=RecurrenceInterval(value=1, unit=RecurrenceUnit.WEEK),
        end=RecurrenceEndCount(count=4),
        weekdays=(Weekday.MO, Weekday.WE),
    )

    result = list(
        iter_candidate_first_dates(rule, date(2026, 5, 4), date(2026, 5, 17))
    )

    assert result == [
        date(2026, 5, 4),   # Mon
        date(2026, 5, 6),   # Wed
        date(2026, 5, 11),  # Mon
        date(2026, 5, 13),  # Wed
    ]


def test_iter_candidate_first_dates_unit_month_yields_every_date() -> None:
    rule = RecurrenceRule(
        interval=RecurrenceInterval(value=1, unit=RecurrenceUnit.MONTH),
        end=RecurrenceEndCount(count=3),
    )

    result = list(
        iter_candidate_first_dates(rule, date(2026, 5, 4), date(2026, 5, 7))
    )

    assert result == [
        date(2026, 5, 4),
        date(2026, 5, 5),
        date(2026, 5, 6),
        date(2026, 5, 7),
    ]


def test_iter_candidate_first_dates_inclusive_bounds_single_day() -> None:
    rule = RecurrenceRule(
        interval=RecurrenceInterval(value=1, unit=RecurrenceUnit.DAY),
        end=RecurrenceEndCount(count=1),
    )

    result = list(
        iter_candidate_first_dates(rule, date(2026, 5, 4), date(2026, 5, 4))
    )

    assert result == [date(2026, 5, 4)]


def test_iter_candidate_first_dates_end_before_start_yields_nothing() -> None:
    rule = RecurrenceRule(
        interval=RecurrenceInterval(value=1, unit=RecurrenceUnit.DAY),
        end=RecurrenceEndCount(count=1),
    )

    result = list(
        iter_candidate_first_dates(rule, date(2026, 5, 8), date(2026, 5, 4))
    )

    assert result == []


def test_iter_candidate_first_dates_unit_week_with_weekdays_no_match_in_window() -> None:
    rule = RecurrenceRule(
        interval=RecurrenceInterval(value=1, unit=RecurrenceUnit.WEEK),
        end=RecurrenceEndCount(count=4),
        weekdays=(Weekday.SA,),
    )

    # Mon May 4 to Fri May 8, no Saturdays inside this window.
    result = list(
        iter_candidate_first_dates(rule, date(2026, 5, 4), date(2026, 5, 8))
    )

    assert result == []
