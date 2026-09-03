from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from scheduling_modal_with_recurring_support.services.availability import (
    MAX_OCCURRENCES,
    SlotAvailability,
    _auth_headers,
    analyse_recurrence,
)
from scheduling_modal_with_recurring_support.services.recurrence import (
    RecurrenceEndCount,
    RecurrenceInterval,
    RecurrenceRule,
    RecurrenceUnit,
    from_legacy_cadence,
)


def _schedule_bundle(schedule_id: str) -> dict:
    return {"entry": [{"resource": {"id": schedule_id}}]}


def _slot_bundle(slots: list[dict]) -> dict:
    return {
        "total": len(slots),
        "entry": [{"resource": s} for s in slots],
    }


def _empty_bundle() -> dict:
    return {"total": 0, "entry": []}


PROVIDER_ID = "e766816672f34a5b866771c773e38f3c"
SCHEDULE_ID = f"Location.1-Staff.{PROVIDER_ID}"


def test_auth_headers() -> None:
    result = _auth_headers("mytoken")
    assert result == {"Authorization": "Bearer mytoken"}


def test_max_occurrences_capped() -> None:
    mock_http = MagicMock()
    schedule_resp = MagicMock()
    schedule_resp.ok = True
    schedule_resp.json.return_value = _schedule_bundle(SCHEDULE_ID)

    slots_resp = MagicMock()
    slots_resp.ok = True
    slots_resp.json.return_value = _empty_bundle()

    mock_http.get.side_effect = [schedule_resp] + [slots_resp] * MAX_OCCURRENCES

    rule = RecurrenceRule(
        interval=RecurrenceInterval(value=1, unit=RecurrenceUnit.WEEK),
        end=RecurrenceEndCount(count=MAX_OCCURRENCES),
    )

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        result = analyse_recurrence(
            fhir_base_url="https://fumage-test.canvasmedical.com",
            access_token="tok",
            provider_id=PROVIDER_ID,
            rule=rule,
            start_date=date(2026, 5, 1),
        )

    assert result.total_count == MAX_OCCURRENCES


def test_analyse_recurrence_returns_available_times() -> None:
    mock_http = MagicMock()
    schedule_resp = MagicMock()
    schedule_resp.ok = True
    schedule_resp.json.return_value = _schedule_bundle(SCHEDULE_ID)

    range_resp = MagicMock()
    range_resp.ok = True
    range_resp.json.return_value = _slot_bundle([
        {"start": "2026-05-01T09:00:00-04:00", "end": "2026-05-01T09:30:00-04:00"},
        {"start": "2026-05-01T10:00:00-04:00", "end": "2026-05-01T10:30:00-04:00"},
        {"start": "2026-05-08T14:00:00-04:00", "end": "2026-05-08T14:30:00-04:00"},
    ])

    mock_http.get.side_effect = [schedule_resp, range_resp]

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        result = analyse_recurrence(
            fhir_base_url="https://fumage-test.canvasmedical.com",
            access_token="tok",
            provider_id=PROVIDER_ID,
            rule=from_legacy_cadence("weekly", 2),
            start_date=date(2026, 5, 1),
        )

    assert result.total_count == 2
    assert result.available_count == 2

    day1 = result.slots[0]
    assert day1.occurrence_date == date(2026, 5, 1)
    assert day1.is_available is True
    assert len(day1.available_times) == 2
    assert day1.available_times[0].start == "2026-05-01T09:00:00-04:00"

    day2 = result.slots[1]
    assert day2.occurrence_date == date(2026, 5, 8)
    assert day2.is_available is True
    assert len(day2.available_times) == 1


def test_analyse_recurrence_filters_out_neighbor_dates() -> None:
    mock_http = MagicMock()
    schedule_resp = MagicMock()
    schedule_resp.ok = True
    schedule_resp.json.return_value = _schedule_bundle(SCHEDULE_ID)

    resp = MagicMock()
    resp.ok = True
    resp.json.return_value = _slot_bundle([
        {"start": "2026-05-01T09:00:00-04:00", "end": "2026-05-01T09:30:00-04:00"},
    ])

    mock_http.get.side_effect = [schedule_resp, resp]

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        result = analyse_recurrence(
            fhir_base_url="https://fumage-test.canvasmedical.com",
            access_token="tok",
            provider_id=PROVIDER_ID,
            rule=from_legacy_cadence("weekly", 1),
            start_date=date(2026, 5, 1),
        )

    slot = result.slots[0]
    assert len(slot.available_times) == 1
    assert slot.available_times[0].start == "2026-05-01T09:00:00-04:00"


def test_analyse_recurrence_no_availability() -> None:
    mock_http = MagicMock()
    schedule_resp = MagicMock()
    schedule_resp.ok = True
    schedule_resp.json.return_value = _schedule_bundle(SCHEDULE_ID)

    empty_resp = MagicMock()
    empty_resp.ok = True
    empty_resp.json.return_value = _empty_bundle()

    mock_http.get.side_effect = [schedule_resp, empty_resp]

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        result = analyse_recurrence(
            fhir_base_url="https://fumage-test.canvasmedical.com",
            access_token="tok",
            provider_id=PROVIDER_ID,
            rule=from_legacy_cadence("weekly", 1),
            start_date=date(2026, 5, 1),
        )

    assert result.available_count == 0
    assert result.slots[0].is_available is False
    assert result.slots[0].available_times == []


def test_resolve_schedule_id_matches_by_provider_id() -> None:
    mock_http = MagicMock()
    schedule_resp = MagicMock()
    schedule_resp.ok = True
    schedule_resp.json.return_value = {
        "entry": [
            {"resource": {"id": "Location.1-Staff.aaaa"}},
            {"resource": {"id": f"Location.1-Staff.{PROVIDER_ID}"}},
        ]
    }

    slots_resp = MagicMock()
    slots_resp.ok = True
    slots_resp.json.return_value = _empty_bundle()

    mock_http.get.side_effect = [schedule_resp, slots_resp]

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        result = analyse_recurrence(
            fhir_base_url="https://fumage-test.canvasmedical.com",
            access_token="tok",
            provider_id=PROVIDER_ID,
            rule=from_legacy_cadence("weekly", 1),
            start_date=date(2026, 5, 1),
        )

    slot_call_url = mock_http.get.call_args_list[1][0][0]
    assert SCHEDULE_ID in slot_call_url


def test_resolve_schedule_id_no_entries_raises() -> None:
    mock_http = MagicMock()
    schedule_resp = MagicMock()
    schedule_resp.ok = True
    schedule_resp.json.return_value = {"entry": []}

    mock_http.get.return_value = schedule_resp

    with (
        patch(
            "scheduling_modal_with_recurring_support.services.availability.Http",
            return_value=mock_http,
        ),
        pytest.raises(ValueError, match="No FHIR Schedule found"),
    ):
        analyse_recurrence(
            fhir_base_url="https://fumage-test.canvasmedical.com",
            access_token="tok",
            provider_id=PROVIDER_ID,
            rule=from_legacy_cadence("weekly", 1),
            start_date=date(2026, 5, 1),
        )


def test_resolve_schedule_id_http_error_raises() -> None:
    mock_http = MagicMock()
    schedule_resp = MagicMock()
    schedule_resp.ok = False
    schedule_resp.status_code = 403
    schedule_resp.text = "Forbidden"

    mock_http.get.return_value = schedule_resp

    with (
        patch(
            "scheduling_modal_with_recurring_support.services.availability.Http",
            return_value=mock_http,
        ),
        pytest.raises(RuntimeError, match="FHIR Schedule lookup failed: 403"),
    ):
        analyse_recurrence(
            fhir_base_url="https://fumage-test.canvasmedical.com",
            access_token="tok",
            provider_id=PROVIDER_ID,
            rule=from_legacy_cadence("monthly", 2),
            start_date=date(2026, 5, 1),
        )


def test_slot_availability_is_immutable() -> None:
    slot = SlotAvailability(
        occurrence_date=date(2026, 5, 1),
        available_times=[],
        is_available=False,
    )
    with pytest.raises((AttributeError, TypeError)):
        slot.is_available = True  # type: ignore[misc]


# ---- aggregate_by_candidate_time ----


def test_aggregate_by_candidate_time_recurring() -> None:
    from scheduling_modal_with_recurring_support.services.availability import aggregate_by_candidate_time

    mock_http = MagicMock()
    schedule_resp = MagicMock()
    schedule_resp.ok = True
    schedule_resp.json.return_value = _schedule_bundle(SCHEDULE_ID)

    range_resp = MagicMock()
    range_resp.ok = True
    range_resp.json.return_value = _slot_bundle([
        {"start": "2026-05-01T09:00:00-04:00", "end": "2026-05-01T09:30:00-04:00"},
        {"start": "2026-05-01T10:00:00-04:00", "end": "2026-05-01T10:30:00-04:00"},
        {"start": "2026-05-08T09:00:00-04:00", "end": "2026-05-08T09:30:00-04:00"},
        {"start": "2026-05-15T10:00:00-04:00", "end": "2026-05-15T10:30:00-04:00"},
    ])

    mock_http.get.side_effect = [schedule_resp, range_resp]

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        result = aggregate_by_candidate_time(
            fhir_base_url="https://fumage-test.canvasmedical.com",
            access_token="tok",
            provider_id=PROVIDER_ID,
            rule=from_legacy_cadence("weekly", 3),
            start_date=date(2026, 5, 1),
            tz_offset_minutes=240,
        )

    assert len(result) == 2
    by_hhmm = {a.hhmm: a for a in result}
    assert by_hhmm["09:00"].available_count == 2
    assert by_hhmm["09:00"].total_count == 3
    assert by_hhmm["09:00"].availability_pct == 66.7
    assert by_hhmm["10:00"].available_count == 2
    assert by_hhmm["10:00"].total_count == 3


def test_aggregate_by_candidate_time_single_visit() -> None:
    from scheduling_modal_with_recurring_support.services.availability import aggregate_by_candidate_time

    mock_http = MagicMock()
    schedule_resp = MagicMock()
    schedule_resp.ok = True
    schedule_resp.json.return_value = _schedule_bundle(SCHEDULE_ID)

    day1_resp = MagicMock()
    day1_resp.ok = True
    day1_resp.json.return_value = _slot_bundle([
        {"start": "2026-05-01T09:00:00-04:00", "end": "2026-05-01T09:30:00-04:00"},
        {"start": "2026-05-01T10:00:00-04:00", "end": "2026-05-01T10:30:00-04:00"},
    ])

    mock_http.get.side_effect = [schedule_resp, day1_resp]

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        result = aggregate_by_candidate_time(
            fhir_base_url="https://fumage-test.canvasmedical.com",
            access_token="tok",
            provider_id=PROVIDER_ID,
            rule=from_legacy_cadence("single", 1),
            start_date=date(2026, 5, 1),
            tz_offset_minutes=240,
        )

    assert len(result) == 2
    for a in result:
        assert a.total_count == 1
        assert a.available_count == 1
        assert a.availability_pct == 100.0


def test_aggregate_by_candidate_time_no_times() -> None:
    from scheduling_modal_with_recurring_support.services.availability import aggregate_by_candidate_time

    mock_http = MagicMock()
    schedule_resp = MagicMock()
    schedule_resp.ok = True
    schedule_resp.json.return_value = _schedule_bundle(SCHEDULE_ID)

    empty_resp = MagicMock()
    empty_resp.ok = True
    empty_resp.json.return_value = _empty_bundle()

    mock_http.get.side_effect = [schedule_resp, empty_resp, empty_resp]

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        result = aggregate_by_candidate_time(
            fhir_base_url="https://fumage-test.canvasmedical.com",
            access_token="tok",
            provider_id=PROVIDER_ID,
            rule=from_legacy_cadence("weekly", 2),
            start_date=date(2026, 5, 1),
            tz_offset_minutes=240,
        )

    assert result == []


def test_analyse_recurrence_accepts_direct_rule_with_weekdays() -> None:
    """A RecurrenceRule built directly (no legacy translation) projects correctly."""
    from scheduling_modal_with_recurring_support.services.recurrence import Weekday

    mock_http = MagicMock()
    schedule_resp = MagicMock()
    schedule_resp.ok = True
    schedule_resp.json.return_value = _schedule_bundle(SCHEDULE_ID)

    empty_resp = MagicMock()
    empty_resp.ok = True
    empty_resp.json.return_value = _empty_bundle()

    mock_http.get.side_effect = [schedule_resp, empty_resp, empty_resp, empty_resp]

    rule = RecurrenceRule(
        interval=RecurrenceInterval(value=1, unit=RecurrenceUnit.WEEK),
        weekdays=(Weekday.MO, Weekday.WE),
        end=RecurrenceEndCount(count=3),
    )

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        result = analyse_recurrence(
            fhir_base_url="https://fumage-test.canvasmedical.com",
            access_token="tok",
            provider_id=PROVIDER_ID,
            rule=rule,
            start_date=date(2026, 5, 4),  # Monday
        )

    assert result.total_count == 3
    occurrence_dates = [s.occurrence_date for s in result.slots]
    assert occurrence_dates == [
        date(2026, 5, 4),
        date(2026, 5, 6),
        date(2026, 5, 11),
    ]


# ---- aggregate_by_first_date ----


def _slot_resp_for_date(d: date) -> MagicMock:
    """Build a slot response with one free time on the given date."""
    resp = MagicMock()
    resp.ok = True
    resp.json.return_value = _slot_bundle(
        [{"start": f"{d.isoformat()}T09:00:00-04:00", "end": f"{d.isoformat()}T09:30:00-04:00"}]
    )
    return resp


def _empty_slot_resp() -> MagicMock:
    resp = MagicMock()
    resp.ok = True
    resp.json.return_value = _empty_bundle()
    return resp


def test_aggregate_by_first_date_orders_by_first_date_ascending() -> None:
    from scheduling_modal_with_recurring_support.services.availability import aggregate_by_first_date

    mock_http = MagicMock()
    schedule_resp = MagicMock()
    schedule_resp.ok = True
    schedule_resp.json.return_value = _schedule_bundle(SCHEDULE_ID)

    # Daily rule with count 1 means one occurrence per candidate (the first
    # date itself). With a 3 day window every day is a candidate, the loop
    # makes one slot lookup per candidate.
    mock_http.get.side_effect = [
        schedule_resp,
        _slot_resp_for_date(date(2026, 5, 4)),
        _slot_resp_for_date(date(2026, 5, 5)),
        _empty_slot_resp(),
    ]

    rule = from_legacy_cadence("single", 1)

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        result = aggregate_by_first_date(
            fhir_base_url="https://fumage-test.canvasmedical.com",
            access_token="tok",
            provider_id=PROVIDER_ID,
            rule=rule,
            window_start=date(2026, 5, 4),
            window_end=date(2026, 5, 6),
        )

    assert [a.first_date for a in result] == [
        date(2026, 5, 4),
        date(2026, 5, 5),
        date(2026, 5, 6),
    ]
    assert result[0].available_count == 1
    assert result[0].total_count == 1
    assert result[0].availability_pct == 100.0
    assert result[2].available_count == 0
    assert result[2].total_count == 1
    assert result[2].availability_pct == 0.0


def test_aggregate_by_first_date_scores_recurring_rule_per_candidate() -> None:
    """A weekly count 3 rule projected from May 4 covers May 4, 11, 18.
    Projected from May 5 covers May 5, 12, 19. Each candidate has its own
    score derived from the per-occurrence slot lookups, fed by the single
    range prefill bundle.
    """
    from scheduling_modal_with_recurring_support.services.availability import aggregate_by_first_date

    mock_http = MagicMock()
    schedule_resp = MagicMock()
    schedule_resp.ok = True
    schedule_resp.json.return_value = _schedule_bundle(SCHEDULE_ID)

    # Single range bundle covering the union of unique dates. May 4, 5, 11,
    # 18, and 19 have entries, May 12 is absent so the prefill writes an
    # empty SlotAvailability for it.
    range_resp = MagicMock()
    range_resp.ok = True
    range_resp.json.return_value = _slot_bundle([
        {"start": "2026-05-04T09:00:00-04:00", "end": "2026-05-04T09:30:00-04:00"},
        {"start": "2026-05-05T09:00:00-04:00", "end": "2026-05-05T09:30:00-04:00"},
        {"start": "2026-05-11T09:00:00-04:00", "end": "2026-05-11T09:30:00-04:00"},
        {"start": "2026-05-18T09:00:00-04:00", "end": "2026-05-18T09:30:00-04:00"},
        {"start": "2026-05-19T09:00:00-04:00", "end": "2026-05-19T09:30:00-04:00"},
    ])

    def fake_get(url: str, headers: dict) -> MagicMock:
        if "Schedule?" in url:
            return schedule_resp
        return range_resp

    mock_http.get.side_effect = fake_get

    rule = from_legacy_cadence("weekly", 3)

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        result = aggregate_by_first_date(
            fhir_base_url="https://fumage-test.canvasmedical.com",
            access_token="tok",
            provider_id=PROVIDER_ID,
            rule=rule,
            window_start=date(2026, 5, 4),
            window_end=date(2026, 5, 5),
        )

    assert len(result) == 2
    by_first = {a.first_date: a for a in result}

    may4 = by_first[date(2026, 5, 4)]
    assert may4.available_count == 3
    assert may4.total_count == 3
    assert may4.availability_pct == 100.0
    assert may4.occurrence_dates == [date(2026, 5, 4), date(2026, 5, 11), date(2026, 5, 18)]

    may5 = by_first[date(2026, 5, 5)]
    assert may5.available_count == 2
    assert may5.total_count == 3
    assert may5.availability_pct == round(2 / 3 * 100, 1)
    assert may5.occurrence_dates == [date(2026, 5, 5), date(2026, 5, 12), date(2026, 5, 19)]


def test_aggregate_by_first_date_collapses_to_single_range_call() -> None:
    """Two adjacent first dates whose occurrence sets overlap should resolve
    inside a single range prefill, not fan out into per date Slot lookups.

    Daily rule, count 2, window May 4 to May 5. Candidate May 4 occurs on
    May 4 and May 5. Candidate May 5 occurs on May 5 and May 6. Without
    range prefill the FHIR slot count would be 3 unique dates plus one
    schedule call. With prefill the slot count drops to one range call.
    """
    from scheduling_modal_with_recurring_support.services.availability import aggregate_by_first_date

    mock_http = MagicMock()
    schedule_resp = MagicMock()
    schedule_resp.ok = True
    schedule_resp.json.return_value = _schedule_bundle(SCHEDULE_ID)

    slot_calls: list[str] = []

    def fake_get(url: str, headers: dict) -> MagicMock:
        if "Schedule?" in url:
            return schedule_resp
        slot_calls.append(url)
        return _empty_slot_resp()

    mock_http.get.side_effect = fake_get

    rule = RecurrenceRule(
        interval=RecurrenceInterval(value=1, unit=RecurrenceUnit.DAY),
        end=RecurrenceEndCount(count=2),
    )

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        aggregate_by_first_date(
            fhir_base_url="https://fumage-test.canvasmedical.com",
            access_token="tok",
            provider_id=PROVIDER_ID,
            rule=rule,
            window_start=date(2026, 5, 4),
            window_end=date(2026, 5, 5),
        )

    assert len(slot_calls) == 1
    assert "_count=500" in slot_calls[0]
    assert "start=2026-05-03" in slot_calls[0]
    assert "end=2026-05-07" in slot_calls[0]


def test_aggregate_by_first_date_empty_window_returns_empty_list() -> None:
    from scheduling_modal_with_recurring_support.services.availability import aggregate_by_first_date

    mock_http = MagicMock()
    schedule_resp = MagicMock()
    schedule_resp.ok = True
    schedule_resp.json.return_value = _schedule_bundle(SCHEDULE_ID)

    mock_http.get.return_value = schedule_resp

    rule = from_legacy_cadence("weekly", 3)

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        result = aggregate_by_first_date(
            fhir_base_url="https://fumage-test.canvasmedical.com",
            access_token="tok",
            provider_id=PROVIDER_ID,
            rule=rule,
            window_start=date(2026, 5, 8),
            window_end=date(2026, 5, 4),
        )

    assert result == []


# ---- iter_free_slots ----


def _slot_resp_with_times(times: list[tuple[str, str]]) -> MagicMock:
    """Build a slot response carrying explicit start/end ISO strings."""
    resp = MagicMock()
    resp.ok = True
    resp.json.return_value = _slot_bundle(
        [{"start": s, "end": e} for s, e in times]
    )
    return resp


def test_iter_free_slots_yields_slots_ordered_by_start() -> None:
    from scheduling_modal_with_recurring_support.services.availability import iter_free_slots

    mock_http = MagicMock()
    schedule_resp = MagicMock()
    schedule_resp.ok = True
    schedule_resp.json.return_value = _schedule_bundle(SCHEDULE_ID)

    day1 = _slot_resp_with_times([
        ("2026-05-04T09:00:00-04:00", "2026-05-04T10:00:00-04:00"),
        ("2026-05-04T11:00:00-04:00", "2026-05-04T12:00:00-04:00"),
    ])
    day2 = _slot_resp_with_times([])
    day3 = _slot_resp_with_times([
        ("2026-05-06T08:00:00-04:00", "2026-05-06T09:00:00-04:00"),
    ])

    mock_http.get.side_effect = [schedule_resp, day1, day2, day3]

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        result = list(
            iter_free_slots(
                fhir_base_url="https://fumage-test.canvasmedical.com",
                access_token="tok",
                provider_id=PROVIDER_ID,
                window_start=date(2026, 5, 4),
                window_end=date(2026, 5, 6),
                limit=10,
            )
        )

    starts = [s.start for s in result]
    assert starts == [
        "2026-05-04T09:00:00-04:00",
        "2026-05-04T11:00:00-04:00",
        "2026-05-06T08:00:00-04:00",
    ]


def test_iter_free_slots_stops_when_limit_reached() -> None:
    from scheduling_modal_with_recurring_support.services.availability import iter_free_slots

    mock_http = MagicMock()
    schedule_resp = MagicMock()
    schedule_resp.ok = True
    schedule_resp.json.return_value = _schedule_bundle(SCHEDULE_ID)

    day1 = _slot_resp_with_times([
        ("2026-05-04T09:00:00-04:00", "2026-05-04T10:00:00-04:00"),
        ("2026-05-04T11:00:00-04:00", "2026-05-04T12:00:00-04:00"),
    ])
    day2 = _slot_resp_with_times([
        ("2026-05-05T13:00:00-04:00", "2026-05-05T14:00:00-04:00"),
    ])
    # Day 3 should never be queried because limit = 2 hits first.
    mock_http.get.side_effect = [schedule_resp, day1, day2]

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        result = list(
            iter_free_slots(
                fhir_base_url="https://fumage-test.canvasmedical.com",
                access_token="tok",
                provider_id=PROVIDER_ID,
                window_start=date(2026, 5, 4),
                window_end=date(2026, 5, 6),
                limit=2,
            )
        )

    assert len(result) == 2
    assert result[0].start == "2026-05-04T09:00:00-04:00"
    assert result[1].start == "2026-05-04T11:00:00-04:00"


def test_iter_free_slots_empty_window_yields_nothing() -> None:
    from scheduling_modal_with_recurring_support.services.availability import iter_free_slots

    mock_http = MagicMock()
    schedule_resp = MagicMock()
    schedule_resp.ok = True
    schedule_resp.json.return_value = _schedule_bundle(SCHEDULE_ID)

    empty = _slot_resp_with_times([])
    mock_http.get.side_effect = [schedule_resp, empty, empty]

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        result = list(
            iter_free_slots(
                fhir_base_url="https://fumage-test.canvasmedical.com",
                access_token="tok",
                provider_id=PROVIDER_ID,
                window_start=date(2026, 5, 4),
                window_end=date(2026, 5, 5),
                limit=10,
            )
        )

    assert result == []


def test_iter_free_slots_inverted_window_yields_nothing() -> None:
    from scheduling_modal_with_recurring_support.services.availability import iter_free_slots

    mock_http = MagicMock()
    # Should not even make a schedule lookup because the iterator returns
    # immediately on an inverted window.
    mock_http.get.side_effect = []

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        result = list(
            iter_free_slots(
                fhir_base_url="https://fumage-test.canvasmedical.com",
                access_token="tok",
                provider_id=PROVIDER_ID,
                window_start=date(2026, 5, 8),
                window_end=date(2026, 5, 4),
                limit=10,
            )
        )

    assert result == []
    mock_http.get.assert_not_called()


# ---- lookup_window ----


def test_lookup_window_buckets_slots_by_local_date() -> None:
    from scheduling_modal_with_recurring_support.services.availability import lookup_window

    mock_http = MagicMock()
    schedule_resp = MagicMock()
    schedule_resp.ok = True
    schedule_resp.json.return_value = _schedule_bundle(SCHEDULE_ID)

    slots_resp = MagicMock()
    slots_resp.ok = True
    slots_resp.json.return_value = _slot_bundle([
        {"start": "2026-05-04T09:00:00-04:00", "end": "2026-05-04T10:00:00-04:00"},
        {"start": "2026-05-04T11:00:00-04:00", "end": "2026-05-04T12:00:00-04:00"},
        {"start": "2026-05-05T13:00:00-04:00", "end": "2026-05-05T14:00:00-04:00"},
    ])

    mock_http.get.side_effect = [schedule_resp, slots_resp]

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        result = lookup_window(
            fhir_base_url="https://fumage-test.canvasmedical.com",
            access_token="tok",
            provider_id=PROVIDER_ID,
            window_start=date(2026, 5, 4),
            window_end=date(2026, 5, 6),
            tz_offset_minutes=240,
        )

    assert "2026-05-04" in result
    assert "2026-05-05" in result
    assert len(result["2026-05-04"]) == 2
    assert result["2026-05-04"][0]["hhmm"] == "09:00"
    assert result["2026-05-04"][0]["start"] == "2026-05-04T09:00:00-04:00"
    assert result["2026-05-04"][1]["hhmm"] == "11:00"
    assert result["2026-05-05"][0]["hhmm"] == "13:00"


def test_lookup_window_makes_one_slot_call_for_window() -> None:
    """The whole point of this helper. Twelve recurrence rows opening their
    own date pickers must not fan out into twelve per day Slot lookups.
    """
    from scheduling_modal_with_recurring_support.services.availability import lookup_window

    mock_http = MagicMock()
    schedule_resp = MagicMock()
    schedule_resp.ok = True
    schedule_resp.json.return_value = _schedule_bundle(SCHEDULE_ID)

    slots_resp = MagicMock()
    slots_resp.ok = True
    slots_resp.json.return_value = _empty_bundle()

    calls: list[str] = []

    def fake_get(url: str, headers: dict) -> MagicMock:
        calls.append(url)
        if "Schedule?" in url:
            return schedule_resp
        return slots_resp

    mock_http.get.side_effect = fake_get

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        lookup_window(
            fhir_base_url="https://fumage-test.canvasmedical.com",
            access_token="tok",
            provider_id=PROVIDER_ID,
            window_start=date(2026, 5, 4),
            window_end=date(2026, 5, 24),
        )

    slot_calls = [c for c in calls if "/Slot?" in c]
    assert len(slot_calls) == 1
    assert "_count=500" in slot_calls[0]
    assert "start=2026-05-04" in slot_calls[0]
    assert "end=2026-05-24" in slot_calls[0]


def test_lookup_window_returns_empty_on_non_ok_response() -> None:
    from scheduling_modal_with_recurring_support.services.availability import lookup_window

    mock_http = MagicMock()
    schedule_resp = MagicMock()
    schedule_resp.ok = True
    schedule_resp.json.return_value = _schedule_bundle(SCHEDULE_ID)

    slots_resp = MagicMock()
    slots_resp.ok = False
    slots_resp.status_code = 502

    mock_http.get.side_effect = [schedule_resp, slots_resp]

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        result = lookup_window(
            fhir_base_url="https://fumage-test.canvasmedical.com",
            access_token="tok",
            provider_id=PROVIDER_ID,
            window_start=date(2026, 5, 4),
            window_end=date(2026, 5, 6),
        )

    assert result == {}


def test_lookup_window_skips_entries_missing_start_or_end() -> None:
    from scheduling_modal_with_recurring_support.services.availability import lookup_window

    mock_http = MagicMock()
    schedule_resp = MagicMock()
    schedule_resp.ok = True
    schedule_resp.json.return_value = _schedule_bundle(SCHEDULE_ID)

    slots_resp = MagicMock()
    slots_resp.ok = True
    slots_resp.json.return_value = {
        "entry": [
            {"resource": {"start": "2026-05-04T09:00:00-04:00", "end": "2026-05-04T10:00:00-04:00"}},
            {"resource": {"start": "2026-05-04T11:00:00-04:00"}},  # missing end
            {"resource": {}},
            {},
        ]
    }

    mock_http.get.side_effect = [schedule_resp, slots_resp]

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        result = lookup_window(
            fhir_base_url="https://fumage-test.canvasmedical.com",
            access_token="tok",
            provider_id=PROVIDER_ID,
            window_start=date(2026, 5, 4),
            window_end=date(2026, 5, 6),
            tz_offset_minutes=240,
        )

    assert result == {
        "2026-05-04": [
            {
                "hhmm": "09:00",
                "start": "2026-05-04T09:00:00-04:00",
                "end": "2026-05-04T10:00:00-04:00",
            }
        ]
    }


def test_lookup_window_respects_tz_offset_for_bucketing() -> None:
    """A FHIR slot at 2026-05-05T01:00:00Z is May 4 at 21:00 in EDT.
    With tz_offset_minutes=240 (EDT), the bucket key must be 2026-05-04.
    """
    from scheduling_modal_with_recurring_support.services.availability import lookup_window

    mock_http = MagicMock()
    schedule_resp = MagicMock()
    schedule_resp.ok = True
    schedule_resp.json.return_value = _schedule_bundle(SCHEDULE_ID)

    slots_resp = MagicMock()
    slots_resp.ok = True
    slots_resp.json.return_value = _slot_bundle([
        {"start": "2026-05-05T01:00:00+00:00", "end": "2026-05-05T02:00:00+00:00"},
    ])

    mock_http.get.side_effect = [schedule_resp, slots_resp]

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        result = lookup_window(
            fhir_base_url="https://fumage-test.canvasmedical.com",
            access_token="tok",
            provider_id=PROVIDER_ID,
            window_start=date(2026, 5, 4),
            window_end=date(2026, 5, 6),
            tz_offset_minutes=240,
        )

    assert "2026-05-04" in result
    assert result["2026-05-04"][0]["hhmm"] == "21:00"


# ---- range prefill ----


def _bundle_for_dates(dates: list[date]) -> MagicMock:
    """Build a single Slot bundle response carrying one entry per date."""
    resp = MagicMock()
    resp.ok = True
    resp.json.return_value = _slot_bundle(
        [
            {
                "start": f"{d.isoformat()}T09:00:00-04:00",
                "end": f"{d.isoformat()}T09:30:00-04:00",
            }
            for d in dates
        ]
    )
    return resp


def test_analyse_recurrence_uses_range_prefill() -> None:
    """analyse_recurrence makes one schedule call plus one range Slot call,
    and never falls back to per date `_check_slot`.
    """
    mock_http = MagicMock()
    schedule_resp = MagicMock()
    schedule_resp.ok = True
    schedule_resp.json.return_value = _schedule_bundle(SCHEDULE_ID)

    range_resp = _bundle_for_dates([
        date(2026, 5, 1),
        date(2026, 5, 8),
        date(2026, 5, 15),
    ])

    slot_calls: list[str] = []

    def fake_get(url: str, headers: dict) -> MagicMock:
        if "Schedule?" in url:
            return schedule_resp
        slot_calls.append(url)
        return range_resp

    mock_http.get.side_effect = fake_get

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        result = analyse_recurrence(
            fhir_base_url="https://fumage-test.canvasmedical.com",
            access_token="tok",
            provider_id=PROVIDER_ID,
            rule=from_legacy_cadence("weekly", 3),
            start_date=date(2026, 5, 1),
        )

    assert len(slot_calls) == 1
    assert "_count=500" in slot_calls[0]
    # The fetch window is padded one day each side so a boundary slot whose
    # clinic date sits just outside the occurrence span can still land on a
    # requested local date once the browser offset is applied.
    assert "start=2026-04-30" in slot_calls[0]
    assert "end=2026-05-16" in slot_calls[0]
    assert result.total_count == 3
    assert result.available_count == 3


def test_aggregate_by_candidate_time_uses_range_prefill() -> None:
    """aggregate_by_candidate_time makes one schedule call plus one range
    Slot call covering all target dates.
    """
    from scheduling_modal_with_recurring_support.services.availability import aggregate_by_candidate_time

    mock_http = MagicMock()
    schedule_resp = MagicMock()
    schedule_resp.ok = True
    schedule_resp.json.return_value = _schedule_bundle(SCHEDULE_ID)

    range_resp = MagicMock()
    range_resp.ok = True
    range_resp.json.return_value = _slot_bundle([
        {"start": "2026-05-01T09:00:00-04:00", "end": "2026-05-01T09:30:00-04:00"},
        {"start": "2026-05-08T09:00:00-04:00", "end": "2026-05-08T09:30:00-04:00"},
        {"start": "2026-05-15T09:00:00-04:00", "end": "2026-05-15T09:30:00-04:00"},
        {"start": "2026-05-22T09:00:00-04:00", "end": "2026-05-22T09:30:00-04:00"},
    ])

    slot_calls: list[str] = []

    def fake_get(url: str, headers: dict) -> MagicMock:
        if "Schedule?" in url:
            return schedule_resp
        slot_calls.append(url)
        return range_resp

    mock_http.get.side_effect = fake_get

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        result = aggregate_by_candidate_time(
            fhir_base_url="https://fumage-test.canvasmedical.com",
            access_token="tok",
            provider_id=PROVIDER_ID,
            rule=from_legacy_cadence("weekly", 4),
            start_date=date(2026, 5, 1),
            tz_offset_minutes=240,
        )

    assert len(slot_calls) == 1
    assert "start=2026-04-30" in slot_calls[0]
    assert "end=2026-05-23" in slot_calls[0]
    assert len(result) == 1
    assert result[0].hhmm == "09:00"
    assert result[0].available_count == 4
    assert result[0].total_count == 4


def test_best_series_availability_matches_window_scorer() -> None:
    """The card scorer best_series_availability and the badge scorer
    series_scores_by_first_date return the same SeriesScore for one provider on
    one start date, so a provider card and a calendar day badge can never
    disagree for that provider and date.
    """
    from scheduling_modal_with_recurring_support.services.availability import (
        best_series_availability,
        series_scores_by_first_date,
    )

    # Weekly count 4 from May 4. Only three of the four occurrence dates carry a
    # 09:00 slot, May 18 is missing, so the best series is a partial 3 of 4.
    occurrence_slots = [
        {"start": "2026-05-04T09:00:00-04:00", "end": "2026-05-04T09:30:00-04:00"},
        {"start": "2026-05-11T09:00:00-04:00", "end": "2026-05-11T09:30:00-04:00"},
        {"start": "2026-05-25T09:00:00-04:00", "end": "2026-05-25T09:30:00-04:00"},
    ]

    def build_http() -> MagicMock:
        mock_http = MagicMock()
        schedule_resp = MagicMock()
        schedule_resp.ok = True
        schedule_resp.json.return_value = _schedule_bundle(SCHEDULE_ID)
        range_resp = MagicMock()
        range_resp.ok = True
        range_resp.json.return_value = _slot_bundle(occurrence_slots)

        def fake_get(url: str, headers: dict) -> MagicMock:
            return schedule_resp if "Schedule?" in url else range_resp

        mock_http.get.side_effect = fake_get
        return mock_http

    rule = from_legacy_cadence("weekly", 4)
    base = "https://fumage-test.canvasmedical.com"

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=build_http(),
    ):
        card_score = best_series_availability(
            fhir_base_url=base,
            access_token="tok",
            provider_id=PROVIDER_ID,
            rule=rule,
            start_date=date(2026, 5, 4),
            tz_offset_minutes=240,
        )

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=build_http(),
    ):
        window = series_scores_by_first_date(
            fhir_base_url=base,
            access_token="tok",
            provider_id=PROVIDER_ID,
            rule=rule,
            window_start=date(2026, 5, 4),
            window_end=date(2026, 5, 4),
            tz_offset_minutes=240,
        )

    badge_score = window[0]
    assert card_score.available_count == 3
    assert card_score.total_count == 4
    assert (
        card_score.available_count,
        card_score.total_count,
        card_score.best_hhmm,
    ) == (
        badge_score.available_count,
        badge_score.total_count,
        badge_score.best_hhmm,
    )


def test_aggregate_by_first_date_uses_range_prefill() -> None:
    """aggregate_by_first_date makes one schedule call plus one range Slot
    call spanning the union of every projected occurrence date, and never
    falls back to per date `_check_slot`.
    """
    from scheduling_modal_with_recurring_support.services.availability import aggregate_by_first_date

    mock_http = MagicMock()
    schedule_resp = MagicMock()
    schedule_resp.ok = True
    schedule_resp.json.return_value = _schedule_bundle(SCHEDULE_ID)

    # Weekly count 4, window May 4 to May 5.
    # Candidate May 4 -> [May 4, May 11, May 18, May 25].
    # Candidate May 5 -> [May 5, May 12, May 19, May 26].
    # Union spans May 4 through May 26.
    range_resp = _bundle_for_dates([
        date(2026, 5, 4),
        date(2026, 5, 5),
        date(2026, 5, 11),
        date(2026, 5, 12),
        date(2026, 5, 18),
        date(2026, 5, 19),
        date(2026, 5, 25),
        date(2026, 5, 26),
    ])

    slot_calls: list[str] = []

    def fake_get(url: str, headers: dict) -> MagicMock:
        if "Schedule?" in url:
            return schedule_resp
        slot_calls.append(url)
        return range_resp

    mock_http.get.side_effect = fake_get

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        result = aggregate_by_first_date(
            fhir_base_url="https://fumage-test.canvasmedical.com",
            access_token="tok",
            provider_id=PROVIDER_ID,
            rule=from_legacy_cadence("weekly", 4),
            window_start=date(2026, 5, 4),
            window_end=date(2026, 5, 5),
        )

    assert len(slot_calls) == 1
    assert "start=2026-05-03" in slot_calls[0]
    assert "end=2026-05-27" in slot_calls[0]
    assert len(result) == 2
    by_first = {a.first_date: a for a in result}
    assert by_first[date(2026, 5, 4)].available_count == 4
    assert by_first[date(2026, 5, 5)].available_count == 4


def test_prefill_chunks_wide_ranges() -> None:
    """A date set whose span exceeds MAX_RANGE_DAYS triggers two chunked
    range calls. The chunks together cover the span and the merged memo
    holds an entry for every input date.
    """
    from scheduling_modal_with_recurring_support.services.availability import (
        MAX_RANGE_DAYS,
        SlotAvailability,
        _prefill_memo_for_range,
    )

    mock_http = MagicMock()

    chunk_calls: list[tuple[str, str]] = []

    def fake_get(url: str, headers: dict) -> MagicMock:
        # Pull start and end query params out of the URL.
        start = url.split("start=", 1)[1].split("&", 1)[0]
        end = url.split("end=", 1)[1].split("&", 1)[0]
        chunk_calls.append((start, end))
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = _empty_bundle()
        return resp

    mock_http.get.side_effect = fake_get

    # Build a date set spanning MAX_RANGE_DAYS + 30 days so chunking fires.
    lo = date(2026, 5, 1)
    hi = lo + timedelta(days=MAX_RANGE_DAYS + 30)
    middle = lo + timedelta(days=MAX_RANGE_DAYS)
    dates = {lo, middle, hi}

    memo: dict[date, SlotAvailability] = {}

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        _prefill_memo_for_range(
            memo,
            fhir_base_url="https://fumage-test.canvasmedical.com",
            access_token="tok",
            schedule_id=SCHEDULE_ID,
            dates=dates,
        )

    assert len(chunk_calls) == 2

    chunk_starts = [date.fromisoformat(s) for s, _ in chunk_calls]
    chunk_ends = [date.fromisoformat(e) for _, e in chunk_calls]

    # Chunks must not overlap and must cover the full span, which is padded
    # one day each side of the requested date set.
    assert chunk_starts[0] == lo - timedelta(days=1)
    assert chunk_ends[1] == hi + timedelta(days=1)
    assert (chunk_ends[0] - chunk_starts[0]).days + 1 <= MAX_RANGE_DAYS
    assert (chunk_ends[1] - chunk_starts[1]).days + 1 <= MAX_RANGE_DAYS
    assert chunk_starts[1] == chunk_ends[0] + timedelta(days=1)

    # Memo holds an entry for every input date.
    for d in dates:
        assert d in memo
        assert memo[d].occurrence_date == d
        assert memo[d].available_times == []
        assert memo[d].is_available is False


def test_fetch_slots_by_date_range_buckets_by_local_date_not_clinic_date() -> None:
    """A Slot stamped in the clinic zone is filed under the scheduler's local
    date, not the bare FHIR date prefix.

    Regression. Fumage stamps each Slot `start` in the
    clinic zone, captured live as e.g. `2026-06-18T16:00:00-07:00`. Bucketing on
    the raw `start[:10]` files that under the clinic date 2026-06-18, while the
    scorer localises the time of day to the browser. For a browser east of the
    clinic the slot's local instant crosses midnight, so the calendar badge and
    the row date combobox disagreed about which day the slot belonged to. The
    fetch now buckets on the localised date so both agree.
    """
    from scheduling_modal_with_recurring_support.services.availability import (
        _fetch_slots_by_date_range,
    )

    # A real boundary slot from the captured localhost bundle: 16:00 Pacific.
    boundary = {"start": "2026-06-18T16:00:00-07:00", "end": "2026-06-18T16:20:00-07:00"}

    mock_http = MagicMock()
    range_resp = MagicMock()
    range_resp.ok = True
    range_resp.json.return_value = _slot_bundle([boundary])
    mock_http.get.return_value = range_resp

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        # Pacific browser, same zone as the clinic: 16:00 local stays on the 18th.
        pacific = _fetch_slots_by_date_range(
            "https://fumage.test", "tok", SCHEDULE_ID,
            date(2026, 6, 18), date(2026, 6, 19), tz_offset_minutes=420,
        )
        # London browser, UTC+1: 16:00 Pacific is 00:00 on the 19th local.
        london = _fetch_slots_by_date_range(
            "https://fumage.test", "tok", SCHEDULE_ID,
            date(2026, 6, 18), date(2026, 6, 19), tz_offset_minutes=-60,
        )

    assert list(pacific.keys()) == [date(2026, 6, 18)]
    assert list(london.keys()) == [date(2026, 6, 19)]


def test_prefill_returns_empty_slot_availability_for_uncovered_dates() -> None:
    """A bundle that contains entries for only some of the requested dates
    leaves the missing dates with `SlotAvailability(d, [], False)` in memo.
    """
    from scheduling_modal_with_recurring_support.services.availability import (
        SlotAvailability,
        _prefill_memo_for_range,
    )

    mock_http = MagicMock()

    range_resp = MagicMock()
    range_resp.ok = True
    range_resp.json.return_value = _slot_bundle([
        {"start": "2026-05-04T09:00:00-04:00", "end": "2026-05-04T09:30:00-04:00"},
        {"start": "2026-05-06T09:00:00-04:00", "end": "2026-05-06T09:30:00-04:00"},
    ])

    mock_http.get.return_value = range_resp

    memo: dict[date, SlotAvailability] = {}
    requested = {date(2026, 5, 4), date(2026, 5, 5), date(2026, 5, 6)}

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        _prefill_memo_for_range(
            memo,
            fhir_base_url="https://fumage-test.canvasmedical.com",
            access_token="tok",
            schedule_id=SCHEDULE_ID,
            dates=requested,
        )

    assert memo[date(2026, 5, 4)].is_available is True
    assert len(memo[date(2026, 5, 4)].available_times) == 1

    assert memo[date(2026, 5, 5)] == SlotAvailability(
        occurrence_date=date(2026, 5, 5),
        available_times=[],
        is_available=False,
    )

    assert memo[date(2026, 5, 6)].is_available is True
    assert len(memo[date(2026, 5, 6)].available_times) == 1


def test_prefill_with_empty_date_set_makes_no_http_call() -> None:
    """An empty input set short circuits without making any Slot lookup."""
    from scheduling_modal_with_recurring_support.services.availability import (
        SlotAvailability,
        _prefill_memo_for_range,
    )

    mock_http = MagicMock()
    mock_http.get.side_effect = AssertionError("no http call expected")

    memo: dict[date, SlotAvailability] = {}

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        _prefill_memo_for_range(
            memo,
            fhir_base_url="https://fumage-test.canvasmedical.com",
            access_token="tok",
            schedule_id=SCHEDULE_ID,
            dates=set(),
        )

    assert memo == {}
    mock_http.get.assert_not_called()


# ---- _resolve_schedule_id fallback to first entry ----


def test_resolve_schedule_id_falls_back_to_first_entry_when_no_id_match() -> None:
    """When no entry ID contains the provider ID, the first entry is returned."""
    from scheduling_modal_with_recurring_support.services.availability import _resolve_schedule_id

    bundle = {
        "entry": [
            {"resource": {"id": "Location.1-Staff.other-provider"}},
            {"resource": {"id": "Location.2-Staff.another-provider"}},
        ]
    }

    mock_http = MagicMock()
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = bundle
    mock_http.get.return_value = mock_resp

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        result = _resolve_schedule_id("https://fumage.test", "tok", "unmatched-provider")

    assert result == "Location.1-Staff.other-provider"


# ---- _fetch_slots_by_date_range edge cases ----


def test_fetch_slots_by_date_range_non_ok_returns_empty() -> None:
    from scheduling_modal_with_recurring_support.services.availability import _fetch_slots_by_date_range

    mock_http = MagicMock()
    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_http.get.return_value = mock_resp

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        result = _fetch_slots_by_date_range(
            "https://fumage.test", "tok", "sched-1",
            date(2026, 5, 1), date(2026, 5, 7),
        )

    assert result == {}


def test_fetch_slots_by_date_range_skips_entries_missing_start_or_end() -> None:
    from scheduling_modal_with_recurring_support.services.availability import _fetch_slots_by_date_range

    bundle = {
        "entry": [
            {"resource": {"start": "2026-05-01T09:00:00", "end": ""}},
            {"resource": {"start": "", "end": "2026-05-01T09:30:00"}},
            {"resource": {"start": "2026-05-01T10:00:00", "end": "2026-05-01T10:30:00"}},
        ]
    }

    mock_http = MagicMock()
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = bundle
    mock_http.get.return_value = mock_resp

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        result = _fetch_slots_by_date_range(
            "https://fumage.test", "tok", "sched-1",
            date(2026, 5, 1), date(2026, 5, 7),
        )

    assert date(2026, 5, 1) in result
    assert len(result[date(2026, 5, 1)]) == 1


def test_fetch_slots_by_date_range_skips_invalid_date_format() -> None:
    from scheduling_modal_with_recurring_support.services.availability import _fetch_slots_by_date_range

    bundle = {
        "entry": [
            {"resource": {"start": "bad-date-format", "end": "2026-05-01T10:30:00"}},
            {"resource": {"start": "2026-05-01T10:00:00", "end": "2026-05-01T10:30:00"}},
        ]
    }

    mock_http = MagicMock()
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = bundle
    mock_http.get.return_value = mock_resp

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        result = _fetch_slots_by_date_range(
            "https://fumage.test", "tok", "sched-1",
            date(2026, 5, 1), date(2026, 5, 7),
        )

    assert len(result) == 1
    assert date(2026, 5, 1) in result


# ---- _prefill_memo chunk merging ----


def test_prefill_memo_multi_chunk_merges_results() -> None:
    """When the date range spans multiple chunks, slots from each chunk are merged."""
    from scheduling_modal_with_recurring_support.services.availability import (
        FreeSlot,
        SlotAvailability,
        _prefill_memo_for_range,
    )

    d1 = date(2026, 5, 1)
    d2 = date(2026, 8, 1)

    chunk1 = {d1: [FreeSlot(start="2026-05-01T09:00:00", end="2026-05-01T09:30:00")]}
    chunk2 = {d2: [FreeSlot(start="2026-08-01T10:00:00", end="2026-08-01T10:30:00")]}

    call_count = [0]

    def fake_fetch(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return chunk1
        return chunk2

    memo: dict[date, SlotAvailability] = {}

    with patch(
        "scheduling_modal_with_recurring_support.services.availability._fetch_slots_by_date_range",
        side_effect=fake_fetch,
    ):
        _prefill_memo_for_range(memo, "https://fumage.test", "tok", "sched-1", {d1, d2})

    assert d1 in memo
    assert d2 in memo
    assert memo[d1].is_available is True
    assert memo[d2].is_available is True


def test_prefill_memo_passes_duration_minutes_to_slot_fetch() -> None:
    """The duration_minutes parameter is threaded into the Fumage Slot URL via _fetch_slots_by_date_range."""
    from scheduling_modal_with_recurring_support.services.availability import (
        SlotAvailability,
        _prefill_memo_for_range,
    )

    captured: dict[str, str] = {}

    mock_http = MagicMock()
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {"entry": []}

    def fake_get(url: str, headers=None):  # noqa: ARG001
        captured["url"] = url
        return mock_resp

    mock_http.get.side_effect = fake_get

    memo: dict[date, SlotAvailability] = {}

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        _prefill_memo_for_range(
            memo,
            "https://fumage.test",
            "tok",
            "sched-1",
            {date(2026, 5, 1)},
            duration_minutes=30,
        )

    assert "&duration=30" in captured["url"]


# ---- analyse_recurrence cache miss path ----


def test_aggregate_by_first_date_slot_for_cache_miss_calls_check_slot() -> None:
    """When prefill is a no-op, slot_for in aggregate_by_first_date triggers _check_slot."""
    from scheduling_modal_with_recurring_support.services.availability import (
        FreeSlot,
        SlotAvailability,
        aggregate_by_first_date,
    )

    rule = from_legacy_cadence("weekly", 1)
    window_start = date(2026, 5, 7)
    window_end = date(2026, 5, 7)
    target_date = date(2026, 5, 7)

    mock_avail = SlotAvailability(
        occurrence_date=target_date,
        available_times=[FreeSlot(start="2026-05-07T09:00:00", end="2026-05-07T09:30:00")],
        is_available=True,
    )

    with (
        patch(
            "scheduling_modal_with_recurring_support.services.availability._resolve_schedule_id",
            return_value=SCHEDULE_ID,
        ),
        patch(
            "scheduling_modal_with_recurring_support.services.availability._prefill_memo_for_range",
        ),
        patch(
            "scheduling_modal_with_recurring_support.services.availability._check_slot",
            return_value=mock_avail,
        ) as mock_check,
    ):
        result = aggregate_by_first_date(
            fhir_base_url="https://fumage.test",
            access_token="tok",
            provider_id=PROVIDER_ID,
            rule=rule,
            window_start=window_start,
            window_end=window_end,
        )

    mock_check.assert_called_once()
    assert result[0].available_count == 1


# ---- _extract_slots non-OK response ----


def test_extract_slots_non_ok_response_returns_empty() -> None:
    from scheduling_modal_with_recurring_support.services.availability import _extract_slots

    mock_resp = MagicMock()
    mock_resp.ok = False

    result = _extract_slots(mock_resp)

    assert result == []


# ---- _filter_non_overlapping (overlapping slots) ----


def test_filter_non_overlapping_collapses_duration_20_interleave() -> None:
    """A duration that is not a multiple of fifteen interleaves the base grid
    and the duration stepped grid, producing overlapping slots.

    Regression. At duration twenty fumage returns 9:00, 9:15, 9:20,
    9:30, 9:40, 9:45 within the hour, where 9:15 to 9:35 overlaps 9:20 to 9:40.
    The greedy filter keeps a slot only when it starts at or after the previous
    kept slot's end, leaving a clean back to back series 9:00, 9:20, 9:40 at the
    real twenty minute length, every offered time genuinely bookable.
    """
    from scheduling_modal_with_recurring_support.services.availability import (
        FreeSlot,
        _filter_non_overlapping,
    )

    raw = [
        FreeSlot(start="2026-06-18T09:00:00-07:00", end="2026-06-18T09:20:00-07:00"),
        FreeSlot(start="2026-06-18T09:15:00-07:00", end="2026-06-18T09:35:00-07:00"),
        FreeSlot(start="2026-06-18T09:20:00-07:00", end="2026-06-18T09:40:00-07:00"),
        FreeSlot(start="2026-06-18T09:30:00-07:00", end="2026-06-18T09:50:00-07:00"),
        FreeSlot(start="2026-06-18T09:40:00-07:00", end="2026-06-18T10:00:00-07:00"),
        FreeSlot(start="2026-06-18T09:45:00-07:00", end="2026-06-18T10:05:00-07:00"),
    ]

    kept = _filter_non_overlapping(raw)

    assert [s.start for s in kept] == [
        "2026-06-18T09:00:00-07:00",
        "2026-06-18T09:20:00-07:00",
        "2026-06-18T09:40:00-07:00",
    ]


def test_filter_non_overlapping_leaves_clean_grid_untouched() -> None:
    """A duration that is a multiple of fifteen yields a clean grid where the
    duration stepped slots are a subset of the base grid, so none overlap and
    every slot is kept.
    """
    from scheduling_modal_with_recurring_support.services.availability import (
        FreeSlot,
        _filter_non_overlapping,
    )

    raw = [
        FreeSlot(start="2026-06-18T09:00:00-07:00", end="2026-06-18T09:30:00-07:00"),
        FreeSlot(start="2026-06-18T09:30:00-07:00", end="2026-06-18T10:00:00-07:00"),
        FreeSlot(start="2026-06-18T10:00:00-07:00", end="2026-06-18T10:30:00-07:00"),
    ]

    kept = _filter_non_overlapping(raw)

    assert kept == raw


def test_filter_non_overlapping_drops_unparseable_slots() -> None:
    """Slots whose start or end will not parse are dropped, matching the
    tolerant style of the extraction code.
    """
    from scheduling_modal_with_recurring_support.services.availability import (
        FreeSlot,
        _filter_non_overlapping,
    )

    raw = [
        FreeSlot(start="not-a-datetime", end="also-bad"),
        FreeSlot(start="2026-06-18T09:00:00-07:00", end="2026-06-18T09:20:00-07:00"),
    ]

    kept = _filter_non_overlapping(raw)

    assert [s.start for s in kept] == ["2026-06-18T09:00:00-07:00"]


def test_extract_slots_collapses_overlapping_pair() -> None:
    """`_extract_slots` applies the non overlapping filter, so an overlapping
    pair from the single day Slot lookup collapses to one bookable start.
    """
    from scheduling_modal_with_recurring_support.services.availability import _extract_slots

    resp = MagicMock()
    resp.ok = True
    resp.json.return_value = _slot_bundle([
        {"start": "2026-06-18T09:15:00-07:00", "end": "2026-06-18T09:35:00-07:00"},
        {"start": "2026-06-18T09:20:00-07:00", "end": "2026-06-18T09:40:00-07:00"},
    ])

    result = _extract_slots(resp)

    assert [s.start for s in result] == ["2026-06-18T09:15:00-07:00"]


def test_fetch_slots_by_date_range_collapses_overlapping_pair_per_bucket() -> None:
    """The range fetch applies the non overlapping filter per local date bucket,
    so the badge and the cards read the same collapsed slot set the time pills
    do.
    """
    from scheduling_modal_with_recurring_support.services.availability import (
        _fetch_slots_by_date_range,
    )

    mock_http = MagicMock()
    range_resp = MagicMock()
    range_resp.ok = True
    range_resp.json.return_value = _slot_bundle([
        {"start": "2026-06-18T09:00:00-07:00", "end": "2026-06-18T09:20:00-07:00"},
        {"start": "2026-06-18T09:15:00-07:00", "end": "2026-06-18T09:35:00-07:00"},
        {"start": "2026-06-18T09:20:00-07:00", "end": "2026-06-18T09:40:00-07:00"},
    ])
    mock_http.get.return_value = range_resp

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        by_date = _fetch_slots_by_date_range(
            "https://fumage.test", "tok", SCHEDULE_ID,
            date(2026, 6, 18), date(2026, 6, 18), tz_offset_minutes=420,
        )

    assert [s.start for s in by_date[date(2026, 6, 18)]] == [
        "2026-06-18T09:00:00-07:00",
        "2026-06-18T09:20:00-07:00",
    ]


# ---- _count_free_slots ----


def test_count_free_slots_returns_entry_count() -> None:
    from scheduling_modal_with_recurring_support.services.availability import _count_free_slots

    bundle: dict[str, list[dict[str, str]]] = {"entry": [{}, {}, {}]}

    mock_http = MagicMock()
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = bundle
    mock_http.get.return_value = mock_resp

    with (
        patch(
            "scheduling_modal_with_recurring_support.services.availability._resolve_schedule_id",
            return_value=SCHEDULE_ID,
        ),
        patch(
            "scheduling_modal_with_recurring_support.services.availability.Http",
            return_value=mock_http,
        ),
    ):
        count = _count_free_slots(
            fhir_base_url="https://fumage.test",
            access_token="tok",
            provider_id=PROVIDER_ID,
            location_id="loc-1",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 7),
        )

    assert count == 3


def test_count_free_slots_non_ok_response_returns_zero() -> None:
    from scheduling_modal_with_recurring_support.services.availability import _count_free_slots

    mock_http = MagicMock()
    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_http.get.return_value = mock_resp

    with (
        patch(
            "scheduling_modal_with_recurring_support.services.availability._resolve_schedule_id",
            return_value=SCHEDULE_ID,
        ),
        patch(
            "scheduling_modal_with_recurring_support.services.availability.Http",
            return_value=mock_http,
        ),
    ):
        count = _count_free_slots(
            fhir_base_url="https://fumage.test",
            access_token="tok",
            provider_id=PROVIDER_ID,
            location_id="loc-1",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 7),
        )

    assert count == 0


# ---- Slot bundle pagination ----
#
# Fumage's default page size silently truncates the response bundle. Peer
# helpers `lookup_window` and `_fetch_slots_by_date_range` already pass
# `_count=500`. These two helpers were missing it, which under counted the
# free slot total and truncated the per day picker.


def test_check_slot_url_passes_count_500() -> None:
    from scheduling_modal_with_recurring_support.services.availability import _check_slot

    mock_http = MagicMock()
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = _empty_bundle()
    mock_http.get.return_value = mock_resp

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        _check_slot(
            fhir_base_url="https://fumage.test",
            access_token="tok",
            schedule_id=SCHEDULE_ID,
            target_date=date(2026, 5, 1),
        )

    call_url = mock_http.get.call_args.args[0]
    assert "_count=500" in call_url
    assert f"schedule={SCHEDULE_ID}" in call_url
    assert "start=2026-05-01" in call_url
    assert "end=2026-05-01" in call_url


def test_count_free_slots_url_passes_count_500() -> None:
    from scheduling_modal_with_recurring_support.services.availability import _count_free_slots

    mock_http = MagicMock()
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = _empty_bundle()
    mock_http.get.return_value = mock_resp

    with (
        patch(
            "scheduling_modal_with_recurring_support.services.availability._resolve_schedule_id",
            return_value=SCHEDULE_ID,
        ),
        patch(
            "scheduling_modal_with_recurring_support.services.availability.Http",
            return_value=mock_http,
        ),
    ):
        _count_free_slots(
            fhir_base_url="https://fumage.test",
            access_token="tok",
            provider_id=PROVIDER_ID,
            location_id="loc-1",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 7),
        )

    call_url = mock_http.get.call_args.args[0]
    assert "_count=500" in call_url
    assert f"schedule={SCHEDULE_ID}" in call_url
    assert "start=2026-05-01" in call_url
    assert "end=2026-05-07" in call_url


# ---- best_series_availability ----


def test_best_series_availability_picks_top_common_time() -> None:
    from scheduling_modal_with_recurring_support.services.availability import (
        best_series_availability,
    )

    mock_http = MagicMock()
    schedule_resp = MagicMock()
    schedule_resp.ok = True
    schedule_resp.json.return_value = _schedule_bundle(SCHEDULE_ID)

    range_resp = MagicMock()
    range_resp.ok = True
    range_resp.json.return_value = _slot_bundle([
        {"start": "2026-05-01T09:00:00-04:00", "end": "2026-05-01T09:30:00-04:00"},
        {"start": "2026-05-01T10:00:00-04:00", "end": "2026-05-01T10:30:00-04:00"},
        {"start": "2026-05-08T09:00:00-04:00", "end": "2026-05-08T09:30:00-04:00"},
        {"start": "2026-05-15T09:00:00-04:00", "end": "2026-05-15T09:30:00-04:00"},
    ])

    mock_http.get.side_effect = [schedule_resp, range_resp]

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        score = best_series_availability(
            fhir_base_url="https://fumage-test.canvasmedical.com",
            access_token="tok",
            provider_id=PROVIDER_ID,
            rule=from_legacy_cadence("weekly", 3),
            start_date=date(2026, 5, 1),
            tz_offset_minutes=240,
        )

    # 09:00 is open on all three weekly dates, 10:00 only on the start date, so
    # the best achievable series is three of three anchored at 09:00.
    assert score.available_count == 3
    assert score.total_count == 3
    assert score.best_hhmm == "09:00"


def test_best_series_availability_zero_when_start_date_closed() -> None:
    from scheduling_modal_with_recurring_support.services.availability import (
        best_series_availability,
    )

    mock_http = MagicMock()
    schedule_resp = MagicMock()
    schedule_resp.ok = True
    schedule_resp.json.return_value = _schedule_bundle(SCHEDULE_ID)

    empty_resp = MagicMock()
    empty_resp.ok = True
    empty_resp.json.return_value = _empty_bundle()

    mock_http.get.side_effect = [schedule_resp, empty_resp, empty_resp]

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        score = best_series_availability(
            fhir_base_url="https://fumage-test.canvasmedical.com",
            access_token="tok",
            provider_id=PROVIDER_ID,
            rule=from_legacy_cadence("weekly", 2),
            start_date=date(2026, 5, 1),
            tz_offset_minutes=240,
        )

    # No candidate time can anchor a series, but the projected occurrence count
    # is still reported so the card can read zero of two.
    assert score.available_count == 0
    assert score.total_count == 2
    assert score.best_hhmm == ""


def test_best_series_availability_threads_duration_into_slot_url() -> None:
    from scheduling_modal_with_recurring_support.services.availability import (
        best_series_availability,
    )

    mock_http = MagicMock()
    schedule_resp = MagicMock()
    schedule_resp.ok = True
    schedule_resp.json.return_value = _schedule_bundle(SCHEDULE_ID)

    range_resp = MagicMock()
    range_resp.ok = True
    range_resp.json.return_value = _slot_bundle([
        {"start": "2026-05-01T09:00:00-04:00", "end": "2026-05-01T10:00:00-04:00"},
    ])

    slot_calls: list[str] = []

    def fake_get(url: str, headers: dict) -> MagicMock:
        if "Schedule?" in url:
            return schedule_resp
        slot_calls.append(url)
        return range_resp

    mock_http.get.side_effect = fake_get

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        best_series_availability(
            fhir_base_url="https://fumage-test.canvasmedical.com",
            access_token="tok",
            provider_id=PROVIDER_ID,
            rule=from_legacy_cadence("single", 1),
            start_date=date(2026, 5, 1),
            tz_offset_minutes=240,
            duration_minutes=90,
        )

    assert slot_calls
    assert "duration=90" in slot_calls[0]


# ---- series_scores_by_first_date ----


def test_series_scores_by_first_date_scores_full_coverage_per_candidate() -> None:
    """Weekly count 3. From May 4 the series covers May 4, 11, 18, all open at
    09:00, so it is a full three of three. From May 5 the series covers May 5,
    12, 19, where 09:00 is open on May 5 and May 19 but not May 12, so the best
    common time is two of three, not full coverage.
    """
    from scheduling_modal_with_recurring_support.services.availability import (
        series_scores_by_first_date,
    )

    mock_http = MagicMock()
    schedule_resp = MagicMock()
    schedule_resp.ok = True
    schedule_resp.json.return_value = _schedule_bundle(SCHEDULE_ID)

    range_resp = MagicMock()
    range_resp.ok = True
    range_resp.json.return_value = _slot_bundle([
        {"start": "2026-05-04T09:00:00-04:00", "end": "2026-05-04T10:00:00-04:00"},
        {"start": "2026-05-05T09:00:00-04:00", "end": "2026-05-05T10:00:00-04:00"},
        {"start": "2026-05-11T09:00:00-04:00", "end": "2026-05-11T10:00:00-04:00"},
        {"start": "2026-05-18T09:00:00-04:00", "end": "2026-05-18T10:00:00-04:00"},
        {"start": "2026-05-19T09:00:00-04:00", "end": "2026-05-19T10:00:00-04:00"},
    ])

    def fake_get(url: str, headers: dict) -> MagicMock:
        if "Schedule?" in url:
            return schedule_resp
        return range_resp

    mock_http.get.side_effect = fake_get

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        result = series_scores_by_first_date(
            fhir_base_url="https://fumage-test.canvasmedical.com",
            access_token="tok",
            provider_id=PROVIDER_ID,
            rule=from_legacy_cadence("weekly", 3),
            window_start=date(2026, 5, 4),
            window_end=date(2026, 5, 5),
            tz_offset_minutes=240,
        )

    by_first = {s.first_date: s for s in result}

    may4 = by_first[date(2026, 5, 4)]
    assert (may4.available_count, may4.total_count, may4.best_hhmm) == (3, 3, "09:00")

    may5 = by_first[date(2026, 5, 5)]
    assert (may5.available_count, may5.total_count, may5.best_hhmm) == (2, 3, "09:00")


def test_series_scores_by_first_date_zero_when_start_date_closed() -> None:
    """A candidate whose own start date has no slot scores zero out of the
    projected count, because a recurring series can only anchor on a start time
    that exists on the start date. Weekly count 2 from May 5, where May 5 is
    closed but May 12 is open, must read zero of two, not one of two.
    """
    from scheduling_modal_with_recurring_support.services.availability import (
        series_scores_by_first_date,
    )

    mock_http = MagicMock()
    schedule_resp = MagicMock()
    schedule_resp.ok = True
    schedule_resp.json.return_value = _schedule_bundle(SCHEDULE_ID)

    range_resp = MagicMock()
    range_resp.ok = True
    # Only the downstream occurrence date is open. The start date May 5 is absent.
    range_resp.json.return_value = _slot_bundle([
        {"start": "2026-05-12T09:00:00-04:00", "end": "2026-05-12T10:00:00-04:00"},
    ])

    def fake_get(url: str, headers: dict) -> MagicMock:
        if "Schedule?" in url:
            return schedule_resp
        return range_resp

    mock_http.get.side_effect = fake_get

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        result = series_scores_by_first_date(
            fhir_base_url="https://fumage-test.canvasmedical.com",
            access_token="tok",
            provider_id=PROVIDER_ID,
            rule=from_legacy_cadence("weekly", 2),
            window_start=date(2026, 5, 5),
            window_end=date(2026, 5, 5),
            tz_offset_minutes=240,
        )

    assert len(result) == 1
    only = result[0]
    assert only.first_date == date(2026, 5, 5)
    assert (only.available_count, only.total_count, only.best_hhmm) == (0, 2, "")


def test_series_scores_by_first_date_inverted_window_returns_empty() -> None:
    from scheduling_modal_with_recurring_support.services.availability import (
        series_scores_by_first_date,
    )

    mock_http = MagicMock()
    mock_http.get.side_effect = AssertionError("no HTTP call on inverted window")

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        result = series_scores_by_first_date(
            fhir_base_url="https://fumage-test.canvasmedical.com",
            access_token="tok",
            provider_id=PROVIDER_ID,
            rule=from_legacy_cadence("weekly", 2),
            window_start=date(2026, 5, 10),
            window_end=date(2026, 5, 4),
        )

    assert result == []


def test_series_scores_by_first_date_one_range_call_and_threads_duration() -> None:
    """The whole window resolves through one schedule call plus one range Slot
    call carrying the real duration, not a per date fan out.
    """
    from scheduling_modal_with_recurring_support.services.availability import (
        series_scores_by_first_date,
    )

    mock_http = MagicMock()
    schedule_resp = MagicMock()
    schedule_resp.ok = True
    schedule_resp.json.return_value = _schedule_bundle(SCHEDULE_ID)

    slot_calls: list[str] = []

    def fake_get(url: str, headers: dict) -> MagicMock:
        if "Schedule?" in url:
            return schedule_resp
        slot_calls.append(url)
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = _empty_bundle()
        return resp

    mock_http.get.side_effect = fake_get

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        series_scores_by_first_date(
            fhir_base_url="https://fumage-test.canvasmedical.com",
            access_token="tok",
            provider_id=PROVIDER_ID,
            rule=from_legacy_cadence("weekly", 3),
            window_start=date(2026, 5, 4),
            window_end=date(2026, 5, 10),
            duration_minutes=90,
        )

    assert len(slot_calls) == 1
    assert "duration=90" in slot_calls[0]
    assert "_count=500" in slot_calls[0]


# ---- elapsed slot filtering on the current day ----


def test_drop_elapsed_slots_keeps_only_future() -> None:
    from scheduling_modal_with_recurring_support.services.availability import (
        FreeSlot,
        _drop_elapsed_slots,
    )

    now = datetime(2026, 6, 24, 17, 0, tzinfo=timezone.utc)
    slots = [
        # 09:00 EDT is 13:00 UTC, before now, elapsed.
        FreeSlot(start="2026-06-24T09:00:00-04:00", end="2026-06-24T09:30:00-04:00"),
        # 15:00 EDT is 19:00 UTC, after now, kept.
        FreeSlot(start="2026-06-24T15:00:00-04:00", end="2026-06-24T15:30:00-04:00"),
    ]

    kept = _drop_elapsed_slots(slots, now)

    assert [s.start for s in kept] == ["2026-06-24T15:00:00-04:00"]


def test_drop_elapsed_slots_boundary_is_strict() -> None:
    from scheduling_modal_with_recurring_support.services.availability import (
        FreeSlot,
        _drop_elapsed_slots,
    )

    # A slot starting exactly at now is treated as already gone.
    now = datetime(2026, 6, 24, 13, 0, tzinfo=timezone.utc)
    slots = [FreeSlot(start="2026-06-24T09:00:00-04:00", end="2026-06-24T09:30:00-04:00")]

    assert _drop_elapsed_slots(slots, now) == []


def _fake_get_for(schedule_resp: MagicMock, range_resp: MagicMock):
    def fake_get(url: str, headers: dict) -> MagicMock:
        if "Schedule?" in url:
            return schedule_resp
        return range_resp

    return fake_get


def test_best_series_availability_drops_elapsed_today_reads_closed() -> None:
    """A single visit on today reads zero once every slot has elapsed, where the
    same call with no now reference still reads one. This is the provider card
    open label fix, the card must not read open when nothing is bookable today."""
    from scheduling_modal_with_recurring_support.services.availability import (
        best_series_availability,
    )

    schedule_resp = MagicMock()
    schedule_resp.ok = True
    schedule_resp.json.return_value = _schedule_bundle(SCHEDULE_ID)

    range_resp = MagicMock()
    range_resp.ok = True
    range_resp.json.return_value = _slot_bundle([
        # The only slot on today, 09:00 EDT is 13:00 UTC.
        {"start": "2026-06-24T09:00:00-04:00", "end": "2026-06-24T09:30:00-04:00"},
    ])

    mock_http = MagicMock()
    mock_http.get.side_effect = _fake_get_for(schedule_resp, range_resp)

    after = datetime(2026, 6, 24, 20, 0, tzinfo=timezone.utc)

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        without_now = best_series_availability(
            fhir_base_url="https://fumage-test.canvasmedical.com",
            access_token="tok",
            provider_id=PROVIDER_ID,
            rule=from_legacy_cadence("single", 1),
            start_date=date(2026, 6, 24),
            tz_offset_minutes=240,
        )
        with_now = best_series_availability(
            fhir_base_url="https://fumage-test.canvasmedical.com",
            access_token="tok",
            provider_id=PROVIDER_ID,
            rule=from_legacy_cadence("single", 1),
            start_date=date(2026, 6, 24),
            tz_offset_minutes=240,
            now=after,
        )

    assert without_now.available_count == 1
    assert with_now.available_count == 0
    assert with_now.total_count == 1


def test_best_series_availability_future_date_untouched_by_now() -> None:
    """A future date keeps its slot even with a now reference, the filter only
    ever changes today."""
    from scheduling_modal_with_recurring_support.services.availability import (
        best_series_availability,
    )

    schedule_resp = MagicMock()
    schedule_resp.ok = True
    schedule_resp.json.return_value = _schedule_bundle(SCHEDULE_ID)

    range_resp = MagicMock()
    range_resp.ok = True
    range_resp.json.return_value = _slot_bundle([
        {"start": "2026-06-30T09:00:00-04:00", "end": "2026-06-30T09:30:00-04:00"},
    ])

    mock_http = MagicMock()
    mock_http.get.side_effect = _fake_get_for(schedule_resp, range_resp)

    now = datetime(2026, 6, 24, 20, 0, tzinfo=timezone.utc)

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        score = best_series_availability(
            fhir_base_url="https://fumage-test.canvasmedical.com",
            access_token="tok",
            provider_id=PROVIDER_ID,
            rule=from_legacy_cadence("single", 1),
            start_date=date(2026, 6, 30),
            tz_offset_minutes=240,
            now=now,
        )

    assert score.available_count == 1


def test_series_scores_by_first_date_drops_elapsed_today_only() -> None:
    """The calendar badge scorer reads zero for a today start whose slot has
    elapsed while a future start the same window still scores one."""
    from scheduling_modal_with_recurring_support.services.availability import (
        series_scores_by_first_date,
    )

    schedule_resp = MagicMock()
    schedule_resp.ok = True
    schedule_resp.json.return_value = _schedule_bundle(SCHEDULE_ID)

    range_resp = MagicMock()
    range_resp.ok = True
    range_resp.json.return_value = _slot_bundle([
        # Today, elapsed against the now below.
        {"start": "2026-06-24T09:00:00-04:00", "end": "2026-06-24T09:30:00-04:00"},
        # Tomorrow, still in the future.
        {"start": "2026-06-25T09:00:00-04:00", "end": "2026-06-25T09:30:00-04:00"},
    ])

    mock_http = MagicMock()
    mock_http.get.side_effect = _fake_get_for(schedule_resp, range_resp)

    now = datetime(2026, 6, 24, 20, 0, tzinfo=timezone.utc)

    with patch(
        "scheduling_modal_with_recurring_support.services.availability.Http",
        return_value=mock_http,
    ):
        scores = series_scores_by_first_date(
            fhir_base_url="https://fumage-test.canvasmedical.com",
            access_token="tok",
            provider_id=PROVIDER_ID,
            rule=from_legacy_cadence("single", 1),
            window_start=date(2026, 6, 24),
            window_end=date(2026, 6, 25),
            tz_offset_minutes=240,
            now=now,
        )

    by_date = {s.first_date: s.available_count for s in scores}
    assert by_date[date(2026, 6, 24)] == 0
    assert by_date[date(2026, 6, 25)] == 1
