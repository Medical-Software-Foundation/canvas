import datetime

from zoneinfo import ZoneInfo

from dataclasses import dataclass

from types import SimpleNamespace

from urgent_care_self_scheduler.slot_search import (
    _calendar_timezone,
    _slot_instant,
    _validate_note_type,
    apply_lead_time,
    block_intervals_for_calendar,
    chunk_window_into_slots,
    compute_slots_for_provider,
    event_occurs_on_date,
    event_window_on_date,
    filter_free_slots,
    parse_calendar_title,
)


@dataclass
class _FakeEvent:
    """Minimal stand-in for canvas_sdk.v1.data.calendar.Event in unit tests."""
    starts_at: datetime.datetime
    ends_at: datetime.datetime
    recurrence: str | None


def _utc(year: int, month: int, day: int, hour: int = 12) -> datetime.datetime:
    return datetime.datetime(year, month, day, hour, tzinfo=datetime.timezone.utc)


def _roles(*role_types: str) -> SimpleNamespace:
    """Build a Staff.roles-like manager whose .all() yields role objects."""
    return SimpleNamespace(all=lambda: [SimpleNamespace(role_type=rt) for rt in role_types])


def _dt(hour: int, minute: int = 0) -> datetime.datetime:
    """Naive datetime on 2026-04-30 at given local time. Used for slot math."""
    return datetime.datetime(2026, 4, 30, hour, minute)


def test_parse_calendar_title_with_name_and_type_only() -> None:
    assert parse_calendar_title("Dr. Smith: Clinic") == ("Dr. Smith", "Clinic", None)


def test_parse_calendar_title_with_location() -> None:
    assert parse_calendar_title("Dr. Smith: Clinic: Main Office") == (
        "Dr. Smith",
        "Clinic",
        "Main Office",
    )


def test_parse_calendar_title_with_colons_in_location() -> None:
    # Locations can contain colons — the parser must rejoin parts beyond the 3rd.
    assert parse_calendar_title("Dr. Smith: Clinic: HQ: Floor 3") == (
        "Dr. Smith",
        "Clinic",
        "HQ: Floor 3",
    )


def test_parse_calendar_title_with_only_one_part() -> None:
    # Malformed title; degrade to (title, "", None) rather than crashing.
    assert parse_calendar_title("Not a real calendar") == ("Not a real calendar", "", None)


def test_chunk_window_into_slots_divides_evenly() -> None:
    slots = chunk_window_into_slots([(_dt(9), _dt(10))], duration_minutes=15)
    assert slots == [
        (_dt(9, 0), _dt(9, 15)),
        (_dt(9, 15), _dt(9, 30)),
        (_dt(9, 30), _dt(9, 45)),
        (_dt(9, 45), _dt(10, 0)),
    ]


def test_chunk_window_into_slots_drops_partial_remainder() -> None:
    # 50 minutes / 20 = 2 full slots + 10 leftover minutes (dropped)
    slots = chunk_window_into_slots([(_dt(9), _dt(9, 50))], duration_minutes=20)
    assert slots == [(_dt(9, 0), _dt(9, 20)), (_dt(9, 20), _dt(9, 40))]


def test_chunk_window_into_slots_handles_multiple_windows() -> None:
    slots = chunk_window_into_slots(
        [(_dt(9), _dt(9, 30)), (_dt(13), _dt(13, 30))], duration_minutes=15
    )
    assert slots == [
        (_dt(9, 0), _dt(9, 15)),
        (_dt(9, 15), _dt(9, 30)),
        (_dt(13, 0), _dt(13, 15)),
        (_dt(13, 15), _dt(13, 30)),
    ]


def test_chunk_window_into_slots_empty_when_window_smaller_than_duration() -> None:
    slots = chunk_window_into_slots([(_dt(9), _dt(9, 10))], duration_minutes=15)
    assert slots == []


def test_chunk_window_into_slots_aligns_starts_to_wall_clock() -> None:
    # Window starts at 9:25 — first slot should be at 9:30 (next 30-min wall-clock
    # boundary), not 9:25. The 5 minutes between 9:25 and 9:30 is unused.
    slots = chunk_window_into_slots([(_dt(9, 25), _dt(11, 0))], duration_minutes=30)
    assert slots == [
        (_dt(9, 30), _dt(10, 0)),
        (_dt(10, 0), _dt(10, 30)),
        (_dt(10, 30), _dt(11, 0)),
    ]


def test_chunk_window_into_slots_alignment_uses_15min_grid_for_15min_slots() -> None:
    # 15-min slots align to :00, :15, :30, :45.
    slots = chunk_window_into_slots([(_dt(9, 7), _dt(10, 0))], duration_minutes=15)
    assert slots == [
        (_dt(9, 15), _dt(9, 30)),
        (_dt(9, 30), _dt(9, 45)),
        (_dt(9, 45), _dt(10, 0)),
    ]


def test_chunk_window_into_slots_dedupes_overlapping_windows() -> None:
    # Overlapping availability windows must not yield duplicate slot start times
    # (the cause of the repeated "8:30 AM" buttons seen in the wizard).
    w1 = (datetime.datetime(2026, 5, 4, 8, 0), datetime.datetime(2026, 5, 4, 9, 0))
    w2 = (datetime.datetime(2026, 5, 4, 8, 30), datetime.datetime(2026, 5, 4, 9, 30))
    slots = chunk_window_into_slots([w1, w2], 30)
    starts = [s for s, _ in slots]
    assert starts == [
        datetime.datetime(2026, 5, 4, 8, 0),
        datetime.datetime(2026, 5, 4, 8, 30),
        datetime.datetime(2026, 5, 4, 9, 0),
    ]
    assert len(starts) == len(set(starts))  # no duplicates


def test_filter_free_slots_drops_overlapping_slot() -> None:
    slots = [(_dt(9), _dt(9, 15)), (_dt(9, 15), _dt(9, 30)), (_dt(9, 30), _dt(9, 45))]
    booked = [(_dt(9, 10), _dt(9, 25))]  # overlaps slot 1 and slot 2
    assert filter_free_slots(slots, booked) == [(_dt(9, 30), _dt(9, 45))]


def test_filter_free_slots_keeps_back_to_back_slot() -> None:
    # Booked appt ends exactly when next slot starts — half-open intervals,
    # the next slot is still bookable.
    slots = [(_dt(9), _dt(9, 15)), (_dt(9, 15), _dt(9, 30))]
    booked = [(_dt(9, 0), _dt(9, 15))]
    assert filter_free_slots(slots, booked) == [(_dt(9, 15), _dt(9, 30))]


def test_filter_free_slots_no_booked_returns_all() -> None:
    slots = [(_dt(9), _dt(9, 15)), (_dt(9, 15), _dt(9, 30))]
    assert filter_free_slots(slots, []) == slots


def test_filter_free_slots_drops_slot_fully_contained_by_appt() -> None:
    slots = [(_dt(9, 30), _dt(9, 45))]
    booked = [(_dt(9, 0), _dt(10, 0))]
    assert filter_free_slots(slots, booked) == []


def test_apply_lead_time_drops_slots_starting_before_threshold() -> None:
    now = _dt(8, 50)
    slots = [(_dt(9), _dt(9, 15)), (_dt(9, 30), _dt(9, 45)), (_dt(10), _dt(10, 15))]
    # 30-minute lead time → threshold is 9:20; first slot (9:00) drops.
    assert apply_lead_time(slots, now=now, lead_time_minutes=30) == [
        (_dt(9, 30), _dt(9, 45)),
        (_dt(10), _dt(10, 15)),
    ]


def test_apply_lead_time_zero_lead_keeps_slot_at_now() -> None:
    now = _dt(9)
    slots = [(_dt(9), _dt(9, 15))]
    assert apply_lead_time(slots, now=now, lead_time_minutes=0) == slots


# ---- event_occurs_on_date (RRULE handling) ----------------------------------


def test_event_occurs_on_date_one_time_only_on_start_date() -> None:
    starts_at = _utc(2026, 5, 1)
    assert event_occurs_on_date(starts_at=starts_at, rrule=None, target_date=datetime.date(2026, 5, 1))
    assert not event_occurs_on_date(starts_at=starts_at, rrule=None, target_date=datetime.date(2026, 5, 2))


def test_event_occurs_on_date_target_before_start_is_false() -> None:
    starts_at = _utc(2026, 5, 1)
    assert not event_occurs_on_date(
        starts_at=starts_at, rrule="RRULE:FREQ=DAILY", target_date=datetime.date(2026, 4, 30)
    )


def test_event_occurs_on_date_daily_every_day() -> None:
    starts_at = _utc(2026, 5, 1)
    for offset in range(0, 5):
        assert event_occurs_on_date(
            starts_at=starts_at,
            rrule="RRULE:FREQ=DAILY",
            target_date=datetime.date(2026, 5, 1) + datetime.timedelta(days=offset),
        )


def test_event_occurs_on_date_daily_with_interval() -> None:
    starts_at = _utc(2026, 5, 1)
    rrule = "RRULE:FREQ=DAILY;INTERVAL=2"
    assert event_occurs_on_date(starts_at=starts_at, rrule=rrule, target_date=datetime.date(2026, 5, 1))
    assert not event_occurs_on_date(starts_at=starts_at, rrule=rrule, target_date=datetime.date(2026, 5, 2))
    assert event_occurs_on_date(starts_at=starts_at, rrule=rrule, target_date=datetime.date(2026, 5, 3))


def test_event_occurs_on_date_weekly_byday() -> None:
    # Starts on Friday 2026-05-01; recurs Mon/Wed/Fri.
    starts_at = _utc(2026, 5, 1)
    rrule = "RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR"
    assert event_occurs_on_date(starts_at=starts_at, rrule=rrule, target_date=datetime.date(2026, 5, 1))   # Fri
    assert event_occurs_on_date(starts_at=starts_at, rrule=rrule, target_date=datetime.date(2026, 5, 4))   # Mon
    assert not event_occurs_on_date(starts_at=starts_at, rrule=rrule, target_date=datetime.date(2026, 5, 5))  # Tue
    assert event_occurs_on_date(starts_at=starts_at, rrule=rrule, target_date=datetime.date(2026, 5, 6))   # Wed


def test_event_occurs_on_date_weekly_without_byday_uses_start_weekday() -> None:
    # RFC 5545: a WEEKLY rule with no BYDAY recurs only on the DTSTART weekday,
    # NOT every day. 2026-05-01 is a Friday.
    starts_at = _utc(2026, 5, 1)
    rrule = "RRULE:FREQ=WEEKLY"
    assert event_occurs_on_date(starts_at=starts_at, rrule=rrule, target_date=datetime.date(2026, 5, 1))   # Fri
    assert event_occurs_on_date(starts_at=starts_at, rrule=rrule, target_date=datetime.date(2026, 5, 8))   # next Fri
    assert not event_occurs_on_date(starts_at=starts_at, rrule=rrule, target_date=datetime.date(2026, 5, 4))  # Mon
    assert not event_occurs_on_date(starts_at=starts_at, rrule=rrule, target_date=datetime.date(2026, 5, 2))  # Sat


def test_event_occurs_on_date_biweekly_skips_off_weeks() -> None:
    # Every-other Friday. On-weeks: 05-01, 05-15, 05-29. Off-weeks: 05-08, 05-22.
    starts_at = _utc(2026, 5, 1)  # Friday
    rrule = "RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=FR"
    assert event_occurs_on_date(starts_at=starts_at, rrule=rrule, target_date=datetime.date(2026, 5, 1))
    assert not event_occurs_on_date(starts_at=starts_at, rrule=rrule, target_date=datetime.date(2026, 5, 8))
    assert event_occurs_on_date(starts_at=starts_at, rrule=rrule, target_date=datetime.date(2026, 5, 15))
    assert not event_occurs_on_date(starts_at=starts_at, rrule=rrule, target_date=datetime.date(2026, 5, 22))
    assert event_occurs_on_date(starts_at=starts_at, rrule=rrule, target_date=datetime.date(2026, 5, 29))


def test_event_occurs_on_date_biweekly_multiday_aligns_to_week_boundary() -> None:
    # INTERVAL=2 with multiple weekdays: on/off is decided by WKST-aligned week
    # boundaries, not a raw day delta from DTSTART. Start Fri 05-01 (week of
    # 04-27 = week 0/on). Week of 05-04 = week 1/off. Week of 05-11 = week 2/on.
    starts_at = _utc(2026, 5, 1)  # Friday
    rrule = "RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE,FR"
    assert event_occurs_on_date(starts_at=starts_at, rrule=rrule, target_date=datetime.date(2026, 5, 1))    # Fri, wk0
    assert not event_occurs_on_date(starts_at=starts_at, rrule=rrule, target_date=datetime.date(2026, 5, 4))   # Mon, wk1 off
    assert not event_occurs_on_date(starts_at=starts_at, rrule=rrule, target_date=datetime.date(2026, 5, 6))   # Wed, wk1 off
    assert event_occurs_on_date(starts_at=starts_at, rrule=rrule, target_date=datetime.date(2026, 5, 11))   # Mon, wk2 on
    assert event_occurs_on_date(starts_at=starts_at, rrule=rrule, target_date=datetime.date(2026, 5, 13))   # Wed, wk2 on


def test_event_occurs_on_date_until_clause_respected() -> None:
    starts_at = _utc(2026, 5, 1)
    rrule = "RRULE:FREQ=DAILY;UNTIL=20260503T235959"
    assert event_occurs_on_date(starts_at=starts_at, rrule=rrule, target_date=datetime.date(2026, 5, 3))
    assert not event_occurs_on_date(starts_at=starts_at, rrule=rrule, target_date=datetime.date(2026, 5, 4))


def test_event_occurs_on_date_until_with_z_suffix() -> None:
    # Real-world Canvas events often serialize UNTIL as YYYYMMDDTHHMMSSZ.
    # The ported parser must NOT silently treat this as "no end".
    starts_at = _utc(2026, 5, 1)
    rrule = "RRULE:FREQ=DAILY;UNTIL=20260503T235959Z"
    assert event_occurs_on_date(starts_at=starts_at, rrule=rrule, target_date=datetime.date(2026, 5, 3))
    assert not event_occurs_on_date(starts_at=starts_at, rrule=rrule, target_date=datetime.date(2026, 5, 4))


def test_event_occurs_on_date_unsupported_freq_returns_false() -> None:
    starts_at = _utc(2026, 5, 1)
    rrule = "RRULE:FREQ=YEARLY"
    assert not event_occurs_on_date(
        starts_at=starts_at, rrule=rrule, target_date=datetime.date(2026, 5, 1)
    )


# ---- event_window_on_date (UTC -> local naive, DST safe) --------------------


def test_event_window_on_date_extracts_local_time_of_day() -> None:
    # 13:00 UTC on 2026-04-30 = 09:00 EDT (NY observes EDT in late April).
    # 17:00 UTC = 13:00 EDT.
    starts_at = datetime.datetime(2026, 4, 30, 13, 0, tzinfo=datetime.timezone.utc)
    ends_at = datetime.datetime(2026, 4, 30, 17, 0, tzinfo=datetime.timezone.utc)
    window = event_window_on_date(
        starts_at=starts_at,
        ends_at=ends_at,
        target_date=datetime.date(2026, 5, 1),
        timezone=ZoneInfo("America/New_York"),
    )
    assert window == (
        datetime.datetime(2026, 5, 1, 9, 0),
        datetime.datetime(2026, 5, 1, 13, 0),
    )


def test_event_window_on_date_preserves_wall_clock_across_dst() -> None:
    # Event was originally created Feb 1 2026 (before DST) at 09:00 EST = 14:00 UTC.
    # Provider semantically means "9am local". On 2026-05-01 (after DST → EDT),
    # the extracted window must still be 09:00–17:00 local naive.
    starts_at = datetime.datetime(2026, 2, 1, 14, 0, tzinfo=datetime.timezone.utc)
    ends_at = datetime.datetime(2026, 2, 1, 22, 0, tzinfo=datetime.timezone.utc)
    window = event_window_on_date(
        starts_at=starts_at,
        ends_at=ends_at,
        target_date=datetime.date(2026, 5, 1),
        timezone=ZoneInfo("America/New_York"),
    )
    assert window == (
        datetime.datetime(2026, 5, 1, 9, 0),
        datetime.datetime(2026, 5, 1, 17, 0),
    )


def test_event_window_on_date_splits_overnight_window_across_midnight() -> None:
    # Overnight availability (22:00–02:00): the end time-of-day is earlier than
    # the start, so the window extends into the following day instead of dropping.
    starts_at = datetime.datetime(2026, 5, 1, 22, 0, tzinfo=datetime.timezone.utc)
    ends_at = datetime.datetime(2026, 5, 1, 2, 0, tzinfo=datetime.timezone.utc)
    window = event_window_on_date(
        starts_at=starts_at,
        ends_at=ends_at,
        target_date=datetime.date(2026, 5, 1),
        timezone=ZoneInfo("UTC"),
    )
    assert window == (
        datetime.datetime(2026, 5, 1, 22, 0),
        datetime.datetime(2026, 5, 2, 2, 0),
    )


def test_event_window_on_date_returns_none_for_zero_length_window() -> None:
    # Equal start/end time-of-day is a degenerate zero-length window — not bookable.
    starts_at = datetime.datetime(2026, 5, 1, 9, 0, tzinfo=datetime.timezone.utc)
    ends_at = datetime.datetime(2026, 5, 1, 9, 0, tzinfo=datetime.timezone.utc)
    window = event_window_on_date(
        starts_at=starts_at,
        ends_at=ends_at,
        target_date=datetime.date(2026, 5, 1),
        timezone=ZoneInfo("UTC"),
    )
    assert window is None


# ---- compute_slots_for_provider (per-provider orchestration) ----------------

# Test setup convenience: window is 3 weekdays starting Mon 2026-05-04 in UTC tz.
_WINDOW_START = datetime.datetime(2026, 5, 4, 0, 0, tzinfo=datetime.timezone.utc)
_WINDOW_END = datetime.datetime(2026, 5, 7, 0, 0, tzinfo=datetime.timezone.utc)
_TZ = ZoneInfo("UTC")
# Lead time of 0 means "now" doesn't filter any slots; tests can override.
_NOW_BEFORE_WINDOW = datetime.datetime(2026, 5, 3, 0, 0, tzinfo=datetime.timezone.utc)


def test_compute_slots_for_provider_chunks_event_window_per_day() -> None:
    # Daily 9–10 UTC event, 15-min slots, no bookings.
    event = _FakeEvent(
        starts_at=datetime.datetime(2026, 5, 4, 9, 0, tzinfo=datetime.timezone.utc),
        ends_at=datetime.datetime(2026, 5, 4, 10, 0, tzinfo=datetime.timezone.utc),
        recurrence="RRULE:FREQ=DAILY",
    )
    slots = compute_slots_for_provider(
        provider_id="prov-1",
        provider_name="Dr. Smith",
        events=[event],
        booked=[],
        window_start=_WINDOW_START,
        window_end=_WINDOW_END,
        timezone=_TZ,
        duration_minutes=15,
        now=_NOW_BEFORE_WINDOW,
        lead_time_minutes=0,
    )
    # 3 days × 4 slots/day = 12.
    assert len(slots) == 12
    assert slots[0]["provider_id"] == "prov-1"
    assert slots[0]["provider_name"] == "Dr. Smith"
    # ISO strings are tz-aware (UTC tz here) so the browser can render them in the
    # patient's local time regardless of the practice tz.
    assert slots[0]["start_iso"] == "2026-05-04T09:00:00+00:00"
    assert slots[0]["end_iso"] == "2026-05-04T09:15:00+00:00"
    assert slots[-1]["start_iso"] == "2026-05-06T09:45:00+00:00"


def test_compute_slots_for_provider_no_events_returns_empty() -> None:
    slots = compute_slots_for_provider(
        provider_id="prov-1",
        provider_name="Dr. Smith",
        events=[],
        booked=[],
        window_start=_WINDOW_START,
        window_end=_WINDOW_END,
        timezone=_TZ,
        duration_minutes=15,
        now=_NOW_BEFORE_WINDOW,
        lead_time_minutes=0,
    )
    assert slots == []


def test_compute_slots_for_provider_subtracts_booked_appointments() -> None:
    event = _FakeEvent(
        starts_at=datetime.datetime(2026, 5, 4, 9, 0, tzinfo=datetime.timezone.utc),
        ends_at=datetime.datetime(2026, 5, 4, 10, 0, tzinfo=datetime.timezone.utc),
        recurrence=None,  # Single occurrence on May 4
    )
    # Booked 9:15–9:30 — should drop that slot only.
    booked = [
        (datetime.datetime(2026, 5, 4, 9, 15), datetime.datetime(2026, 5, 4, 9, 30)),
    ]
    slots = compute_slots_for_provider(
        provider_id="prov-1",
        provider_name="Dr. Smith",
        events=[event],
        booked=booked,
        window_start=_WINDOW_START,
        window_end=_WINDOW_END,
        timezone=_TZ,
        duration_minutes=15,
        now=_NOW_BEFORE_WINDOW,
        lead_time_minutes=0,
    )
    times = [(s["start_iso"], s["end_iso"]) for s in slots]
    assert times == [
        ("2026-05-04T09:00:00+00:00", "2026-05-04T09:15:00+00:00"),
        ("2026-05-04T09:30:00+00:00", "2026-05-04T09:45:00+00:00"),
        ("2026-05-04T09:45:00+00:00", "2026-05-04T10:00:00+00:00"),
    ]


def test_compute_slots_for_provider_applies_lead_time() -> None:
    event = _FakeEvent(
        starts_at=datetime.datetime(2026, 5, 4, 9, 0, tzinfo=datetime.timezone.utc),
        ends_at=datetime.datetime(2026, 5, 4, 10, 0, tzinfo=datetime.timezone.utc),
        recurrence=None,
    )
    # now=8:50 UTC, lead 30min → threshold 9:20 → drop 9:00 slot.
    now = datetime.datetime(2026, 5, 4, 8, 50, tzinfo=datetime.timezone.utc)
    slots = compute_slots_for_provider(
        provider_id="prov-1",
        provider_name="Dr. Smith",
        events=[event],
        booked=[],
        window_start=now,
        window_end=_WINDOW_END,
        timezone=_TZ,
        duration_minutes=15,
        now=now,
        lead_time_minutes=30,
    )
    assert [s["start_iso"] for s in slots] == [
        "2026-05-04T09:30:00+00:00",
        "2026-05-04T09:45:00+00:00",
    ]


def test_compute_slots_for_provider_skips_event_outside_window() -> None:
    # Event recurs only on May 10 (outside the May 4–6 window).
    event = _FakeEvent(
        starts_at=datetime.datetime(2026, 5, 10, 9, 0, tzinfo=datetime.timezone.utc),
        ends_at=datetime.datetime(2026, 5, 10, 10, 0, tzinfo=datetime.timezone.utc),
        recurrence=None,
    )
    slots = compute_slots_for_provider(
        provider_id="prov-1",
        provider_name="Dr. Smith",
        events=[event],
        booked=[],
        window_start=_WINDOW_START,
        window_end=_WINDOW_END,
        timezone=_TZ,
        duration_minutes=15,
        now=_NOW_BEFORE_WINDOW,
        lead_time_minutes=0,
    )
    assert slots == []


# ---- _validate_note_type ---------------------------------------------------


def _good_note_type(**overrides: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "is_scheduleable": True,
        "is_scheduleable_via_patient_portal": True,
        "online_duration": 15,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_validate_note_type_accepts_full_config() -> None:
    assert _validate_note_type(_good_note_type()) is None


def test_validate_note_type_rejects_when_not_scheduleable() -> None:
    assert _validate_note_type(_good_note_type(is_scheduleable=False)) == "not is_scheduleable"


def test_validate_note_type_rejects_when_not_portal_scheduleable() -> None:
    assert (
        _validate_note_type(_good_note_type(is_scheduleable_via_patient_portal=False))
        == "not is_scheduleable_via_patient_portal"
    )


def test_validate_note_type_rejects_zero_duration() -> None:
    assert _validate_note_type(_good_note_type(online_duration=0)) == "online_duration=0"


def test_validate_note_type_rejects_none_duration() -> None:
    assert _validate_note_type(_good_note_type(online_duration=None)) == "online_duration=0"


# ---- find_available_slots orchestrator (SDK-mocked) -------------------------


def _set_note_type_filter(mocker, note_types):
    from canvas_sdk.v1.data.note import NoteType
    return mocker.patch.object(NoteType.objects, "filter", return_value=list(note_types))


def _set_calendar_filter(mocker, calendars):
    from canvas_sdk.v1.data.calendar import Calendar
    return mocker.patch.object(Calendar.objects, "filter", return_value=list(calendars))


def _set_staff_filter(mocker, staff):
    """Staff.objects.filter(active=True, roles=_roles("PROVIDER")).prefetch_related('roles') chain."""
    from canvas_sdk.v1.data.staff import Staff
    chain = SimpleNamespace(prefetch_related=lambda *a, **k: list(staff))
    return mocker.patch.object(Staff.objects, "filter", return_value=chain)


class _EventQS(list):
    """List that also answers .distinct() — supports both the availability fetch
    (Event.objects.filter(...).distinct()) and the admin fetch (direct iteration)."""

    def distinct(self) -> "list":
        return list(self)


def _set_event_filter(mocker, events):
    """Event.objects.filter(...) → iterable QS that also supports .distinct()."""
    from canvas_sdk.v1.data.calendar import Event
    return mocker.patch.object(Event.objects, "filter", return_value=_EventQS(events))


def _set_appointment_filter(mocker, appointments):
    """Appointment.objects.filter(...).exclude(...).only(...) chain."""
    from canvas_sdk.v1.data.appointment import Appointment
    chain = SimpleNamespace(
        exclude=lambda **_: SimpleNamespace(only=lambda *_a: list(appointments))
    )
    return mocker.patch.object(Appointment.objects, "filter", return_value=chain)


def _good_nt(**overrides):
    base = dict(
        is_active=True,
        is_scheduleable=True,
        is_scheduleable_via_patient_portal=True,
        online_duration=15,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


_DEFAULT_WINDOW_START = datetime.datetime(2026, 5, 4, 0, 0, tzinfo=datetime.timezone.utc)
_DEFAULT_WINDOW_END = datetime.datetime(2026, 5, 7, 0, 0, tzinfo=datetime.timezone.utc)
_DEFAULT_NOW = datetime.datetime(2026, 5, 3, 0, 0, tzinfo=datetime.timezone.utc)


def _call_find_slots(**overrides):
    from urgent_care_self_scheduler.slot_search import find_available_slots
    kwargs = dict(
        note_type_name="Urgent Care",
        window_start=_DEFAULT_WINDOW_START,
        window_end=_DEFAULT_WINDOW_END,
        practice_timezone=ZoneInfo("UTC"),
        now=_DEFAULT_NOW,
        lead_time_minutes=0,
    )
    kwargs.update(overrides)
    return find_available_slots(**kwargs)


def test_find_available_slots_returns_empty_when_no_matching_note_type(mocker):
    _set_note_type_filter(mocker, [])
    assert _call_find_slots() == []


def test_find_available_slots_returns_empty_when_multiple_matching_note_types(mocker):
    _set_note_type_filter(mocker, [_good_nt(), _good_nt()])
    assert _call_find_slots() == []


def test_find_available_slots_returns_empty_when_note_type_misconfigured(mocker):
    _set_note_type_filter(mocker, [_good_nt(online_duration=0)])
    assert _call_find_slots() == []


def test_find_available_slots_returns_empty_when_no_clinic_calendars(mocker):
    _set_note_type_filter(mocker, [_good_nt()])
    _set_calendar_filter(mocker, [])
    assert _call_find_slots() == []


def test_find_available_slots_returns_empty_when_no_staff_match_calendar_titles(mocker):
    _set_note_type_filter(mocker, [_good_nt()])
    _set_calendar_filter(
        mocker,
        [SimpleNamespace(id="cal-1", dbid=10, title="Dr. Nobody: Clinic")],
    )
    # Active staff exists but full_name doesn't match the calendar title.
    _set_staff_filter(
        mocker,
        [SimpleNamespace(id="s1", dbid=1, full_name="Dr. SomeoneElse", active=True, roles=_roles("PROVIDER"))],
    )
    assert _call_find_slots() == []


def test_find_available_slots_skips_calendar_when_provider_name_is_ambiguous(mocker):
    # Two active staff share a full_name; a calendar title can't disambiguate
    # them, so that name is dropped rather than risk booking the wrong provider.
    _set_note_type_filter(mocker, [_good_nt()])
    _set_calendar_filter(
        mocker,
        [SimpleNamespace(id="cal-1", dbid=10, title="Dr. Smith: Clinic")],
    )
    _set_staff_filter(
        mocker,
        [
            SimpleNamespace(id="s1", dbid=1, full_name="Dr. Smith", active=True, roles=_roles("PROVIDER")),
            SimpleNamespace(id="s2", dbid=2, full_name="Dr. Smith", active=True, roles=_roles("PROVIDER")),
        ],
    )
    assert _call_find_slots() == []


def test_find_available_slots_excludes_non_clinical_staff(mocker):
    # An active Staff with no clinical role (e.g. an exam room) owns a clinic
    # calendar but must never be offered as a bookable provider.
    _set_note_type_filter(mocker, [_good_nt()])
    _set_calendar_filter(
        mocker, [SimpleNamespace(id="cal-r", dbid=20, title="Room 1: Clinic")]
    )
    _set_staff_filter(
        mocker,
        [SimpleNamespace(id="r1", dbid=1, full_name="Room 1", active=True, roles=_roles("NON-LICENSED"))],
    )
    assert _call_find_slots() == []


def test_find_available_slots_includes_provider_by_credential_abbreviation(mocker):
    # A staff whose role isn't typed PROVIDER but carries a clinician credential
    # abbreviation (MD/DO/NP/...) is still bookable.
    _set_note_type_filter(mocker, [_good_nt()])
    cal = SimpleNamespace(id="cal-1", dbid=10, title="Dr. Smith: Clinic")
    _set_calendar_filter(mocker, [cal])
    role = SimpleNamespace(role_type="LICENSED", public_abbreviation="MD")
    staff = SimpleNamespace(
        id="s1", dbid=1, full_name="Dr. Smith", active=True,
        roles=SimpleNamespace(all=lambda: [role]),
    )
    _set_staff_filter(mocker, [staff])
    event = SimpleNamespace(
        starts_at=datetime.datetime(2026, 5, 4, 9, tzinfo=datetime.timezone.utc),
        ends_at=datetime.datetime(2026, 5, 4, 10, tzinfo=datetime.timezone.utc),
        recurrence=None,
        calendar_id=cal.dbid,
    )
    _set_event_filter(mocker, [event])
    _set_appointment_filter(mocker, [])

    slots = _call_find_slots()
    assert len(slots) == 4
    assert slots[0]["provider_name"] == "Dr. Smith"


def test_find_available_slots_returns_slots_for_matched_provider(mocker):
    _set_note_type_filter(mocker, [_good_nt()])
    cal = SimpleNamespace(id="cal-1", dbid=10, title="Dr. Smith: Clinic")
    _set_calendar_filter(mocker, [cal])
    staff = SimpleNamespace(id="s1", dbid=1, full_name="Dr. Smith", active=True, roles=_roles("PROVIDER"))
    _set_staff_filter(mocker, [staff])

    # One event covering 9-10 UTC daily, no recurrence. Note: Event.calendar_id
    # is the FK to Calendar.dbid (int), not Calendar.id (UUID).
    event = SimpleNamespace(
        starts_at=datetime.datetime(2026, 5, 4, 9, tzinfo=datetime.timezone.utc),
        ends_at=datetime.datetime(2026, 5, 4, 10, tzinfo=datetime.timezone.utc),
        recurrence=None,
        calendar_id=cal.dbid,
    )
    _set_event_filter(mocker, [event])
    _set_appointment_filter(mocker, [])  # no booked appointments

    slots = _call_find_slots()
    # 1-hour window, 15-min slots → 4 slots.
    assert len(slots) == 4
    assert slots[0]["provider_id"] == "s1"
    assert slots[0]["provider_name"] == "Dr. Smith"
    assert slots[0]["start_iso"] == "2026-05-04T09:00:00+00:00"


def test_find_available_slots_skips_note_type_resolution_when_provided(mocker):
    # Passing a pre-resolved note_type (as BookAPI does) must NOT re-query NoteType.
    from canvas_sdk.v1.data.note import NoteType
    nt_filter = mocker.patch.object(NoteType.objects, "filter")
    cal = SimpleNamespace(id="cal-1", dbid=10, title="Dr. Smith: Clinic")
    _set_calendar_filter(mocker, [cal])
    _set_staff_filter(
        mocker, [SimpleNamespace(id="s1", dbid=1, full_name="Dr. Smith", active=True, roles=_roles("PROVIDER"))]
    )
    event = SimpleNamespace(
        starts_at=datetime.datetime(2026, 5, 4, 9, tzinfo=datetime.timezone.utc),
        ends_at=datetime.datetime(2026, 5, 4, 10, tzinfo=datetime.timezone.utc),
        recurrence=None,
        calendar_id=cal.dbid,
    )
    _set_event_filter(mocker, [event])
    _set_appointment_filter(mocker, [])
    note_type = SimpleNamespace(
        id="nt-1",
        online_duration=15,
        is_active=True,
        is_scheduleable=True,
        is_scheduleable_via_patient_portal=True,
    )

    slots = _call_find_slots(note_type=note_type)
    assert len(slots) == 4
    nt_filter.assert_not_called()


def test_find_available_slots_skips_calendar_when_no_events_match(mocker):
    _set_note_type_filter(mocker, [_good_nt()])
    cal = SimpleNamespace(id="cal-1", dbid=10, title="Dr. Smith: Clinic")
    _set_calendar_filter(mocker, [cal])
    staff = SimpleNamespace(id="s1", dbid=1, full_name="Dr. Smith", active=True, roles=_roles("PROVIDER"))
    _set_staff_filter(mocker, [staff])
    _set_event_filter(mocker, [])  # no events for this calendar
    _set_appointment_filter(mocker, [])
    assert _call_find_slots() == []


def test_find_available_slots_subtracts_booked_appointments(mocker):
    _set_note_type_filter(mocker, [_good_nt()])
    cal = SimpleNamespace(id="cal-1", dbid=10, title="Dr. Smith: Clinic")
    _set_calendar_filter(mocker, [cal])
    staff = SimpleNamespace(id="s1", dbid=1, full_name="Dr. Smith", active=True, roles=_roles("PROVIDER"))
    _set_staff_filter(mocker, [staff])
    event = SimpleNamespace(
        starts_at=datetime.datetime(2026, 5, 4, 9, tzinfo=datetime.timezone.utc),
        ends_at=datetime.datetime(2026, 5, 4, 10, tzinfo=datetime.timezone.utc),
        recurrence=None,
        calendar_id=cal.dbid,
    )
    _set_event_filter(mocker, [event])
    booked = SimpleNamespace(
        provider_id=1,
        start_time=datetime.datetime(2026, 5, 4, 9, 15, tzinfo=datetime.timezone.utc),
        duration_minutes=15,
    )
    _set_appointment_filter(mocker, [booked])

    slots = _call_find_slots()
    times = [s["start_iso"] for s in slots]
    # 9:15-9:30 slot is booked → drops from result.
    assert "2026-05-04T09:15:00+00:00" not in times
    assert len(slots) == 3


def test_find_available_slots_sorts_and_caps_results(mocker):
    _set_note_type_filter(mocker, [_good_nt()])
    # Three providers with same single event; expect ordering by start time.
    cals = [
        SimpleNamespace(id=f"cal-{i}", dbid=10 + i, title=f"Dr. {n}: Clinic")
        for i, n in enumerate(["Alpha", "Bravo", "Charlie"])
    ]
    _set_calendar_filter(mocker, cals)
    staff = [
        SimpleNamespace(id=f"s{i}", dbid=i + 1, full_name=f"Dr. {n}", active=True, roles=_roles("PROVIDER"))
        for i, n in enumerate(["Alpha", "Bravo", "Charlie"])
    ]
    _set_staff_filter(mocker, staff)
    events = [
        SimpleNamespace(
            starts_at=datetime.datetime(2026, 5, 4, 9, tzinfo=datetime.timezone.utc),
            ends_at=datetime.datetime(2026, 5, 4, 10, tzinfo=datetime.timezone.utc),
            recurrence=None,
            calendar_id=cal.dbid,
        )
        for cal in cals
    ]
    _set_event_filter(mocker, events)
    _set_appointment_filter(mocker, [])

    slots = _call_find_slots(max_results=2)
    # max_results caps PER PROVIDER: 3 providers × 2 = 6 (not a global cap of 2),
    # so every provider is represented rather than crowded out.
    assert len(slots) == 6
    assert {s["provider_name"] for s in slots} == {"Dr. Alpha", "Dr. Bravo", "Dr. Charlie"}
    # Sorted by absolute instant ascending.
    instants = [_slot_instant(s) for s in slots]
    assert instants == sorted(instants)


def test_find_available_slots_dedupes_provider_with_multiple_clinic_calendars(mocker):
    _set_note_type_filter(mocker, [_good_nt()])
    cals = [
        SimpleNamespace(id="cal-1", dbid=10, title="Dr. Smith: Clinic"),
        SimpleNamespace(id="cal-2", dbid=11, title="Dr. Smith: Clinic: Annex"),
    ]
    _set_calendar_filter(mocker, cals)
    staff = SimpleNamespace(id="s1", dbid=1, full_name="Dr. Smith", active=True, roles=_roles("PROVIDER"))
    _set_staff_filter(mocker, [staff])
    # Each calendar has the same daily 9-10 event.
    events = [
        SimpleNamespace(
            starts_at=datetime.datetime(2026, 5, 4, 9, tzinfo=datetime.timezone.utc),
            ends_at=datetime.datetime(2026, 5, 4, 10, tzinfo=datetime.timezone.utc),
            recurrence=None,
            calendar_id=cal.dbid,
        )
        for cal in cals
    ]
    _set_event_filter(mocker, events)
    _set_appointment_filter(mocker, [])

    slots = _call_find_slots()
    # Same provider should only contribute slots once.
    assert len(slots) == 4


def test_find_available_slots_stamps_location_from_index(mocker):
    # Each slot carries the location resolved from its calendar's title suffix,
    # so BookAPI can book into the right site and the wizard can label it.
    _set_note_type_filter(mocker, [_good_nt()])
    cal = SimpleNamespace(
        id="cal-1", dbid=10, title="Dr. Smith: Clinic: California Location", timezone=ZoneInfo("UTC")
    )
    _set_calendar_filter(mocker, [cal])
    staff = SimpleNamespace(id="s1", dbid=1, full_name="Dr. Smith", active=True, roles=_roles("PROVIDER"))
    _set_staff_filter(mocker, [staff])
    event = SimpleNamespace(
        starts_at=datetime.datetime(2026, 5, 4, 9, tzinfo=datetime.timezone.utc),
        ends_at=datetime.datetime(2026, 5, 4, 10, tzinfo=datetime.timezone.utc),
        recurrence=None,
        calendar_id=cal.dbid,
    )
    _set_event_filter(mocker, [event])
    _set_appointment_filter(mocker, [])

    slots = _call_find_slots(location_index={"California Location": ("loc-ca", "California")})
    assert slots
    assert all(s["location_id"] == "loc-ca" and s["location_name"] == "California" for s in slots)


def test_find_available_slots_location_unknown_when_no_suffix_or_index(mocker):
    # A location-less calendar title yields no location; a suffix missing from the
    # index keeps the raw suffix as the display name with no id.
    _set_note_type_filter(mocker, [_good_nt()])
    cal = SimpleNamespace(id="cal-1", dbid=10, title="Dr. Smith: Clinic", timezone=ZoneInfo("UTC"))
    _set_calendar_filter(mocker, [cal])
    staff = SimpleNamespace(id="s1", dbid=1, full_name="Dr. Smith", active=True, roles=_roles("PROVIDER"))
    _set_staff_filter(mocker, [staff])
    event = SimpleNamespace(
        starts_at=datetime.datetime(2026, 5, 4, 9, tzinfo=datetime.timezone.utc),
        ends_at=datetime.datetime(2026, 5, 4, 10, tzinfo=datetime.timezone.utc),
        recurrence=None,
        calendar_id=cal.dbid,
    )
    _set_event_filter(mocker, [event])
    _set_appointment_filter(mocker, [])

    slots = _call_find_slots()  # no location_index
    assert slots
    assert all(s["location_id"] is None and s["location_name"] is None for s in slots)


def test_find_available_slots_drops_location_label_when_suffix_unmatched(mocker):
    # A calendar whose location suffix matches no PracticeLocation.full_name must
    # NOT show a misleading label — drop both id and name (booking falls back to the
    # active location). Guards against label-says-X-books-Y.
    _set_note_type_filter(mocker, [_good_nt()])
    cal = SimpleNamespace(
        id="cal-1", dbid=10, title="Dr. Smith: Clinic: Reno Office", timezone=ZoneInfo("UTC")
    )
    _set_calendar_filter(mocker, [cal])
    staff = SimpleNamespace(id="s1", dbid=1, full_name="Dr. Smith", active=True, roles=_roles("PROVIDER"))
    _set_staff_filter(mocker, [staff])
    event = SimpleNamespace(
        starts_at=datetime.datetime(2026, 5, 4, 9, tzinfo=datetime.timezone.utc),
        ends_at=datetime.datetime(2026, 5, 4, 10, tzinfo=datetime.timezone.utc),
        recurrence=None,
        calendar_id=cal.dbid,
    )
    _set_event_filter(mocker, [event])
    _set_appointment_filter(mocker, [])

    # "Reno Office" is NOT in the index → no label, no id (not the raw suffix).
    slots = _call_find_slots(location_index={"California Location": ("loc-ca", "California")})
    assert slots
    assert all(s["location_id"] is None and s["location_name"] is None for s in slots)


def test_find_available_slots_subtracts_administrative_block_across_timezones(mocker):
    # The reason blocks are converted to absolute time: a block authored on an
    # Eastern admin calendar must remove the coinciding slot from a Pacific clinic
    # calendar. Uses distinct tz on each calendar.
    _set_note_type_filter(mocker, [_good_nt()])
    clinic = SimpleNamespace(
        id="cal-c", dbid=10, title="Dr. Smith: Clinic: West", timezone=ZoneInfo("America/Los_Angeles")
    )
    admin = SimpleNamespace(
        id="cal-a", dbid=20, title="Dr. Smith: Administrative: East", timezone=ZoneInfo("America/New_York")
    )
    _set_calendar_filter(mocker, [clinic, admin])
    staff = SimpleNamespace(id="s1", dbid=1, full_name="Dr. Smith", active=True, roles=_roles("PROVIDER"))
    _set_staff_filter(mocker, [staff])
    # Clinic availability 9:00-10:00 PDT == 16:00-17:00 UTC.
    clinic_event = SimpleNamespace(
        starts_at=datetime.datetime(2026, 5, 4, 16, tzinfo=datetime.timezone.utc),
        ends_at=datetime.datetime(2026, 5, 4, 17, tzinfo=datetime.timezone.utc),
        recurrence=None,
        calendar_id=clinic.dbid,
    )
    # Block 16:00-16:15 UTC (== 12:00 EDT on the Eastern admin calendar) — coincides
    # with the 9:00 AM PDT clinic slot.
    block_event = SimpleNamespace(
        starts_at=datetime.datetime(2026, 5, 4, 16, tzinfo=datetime.timezone.utc),
        ends_at=datetime.datetime(2026, 5, 4, 16, 15, tzinfo=datetime.timezone.utc),
        recurrence=None,
        calendar_id=admin.dbid,
    )
    _set_event_filter(mocker, [clinic_event, block_event])
    _set_appointment_filter(mocker, [])

    slots = _call_find_slots()
    times = [s["start_iso"] for s in slots]
    # The 9:00 AM PDT slot (16:00 UTC) is blocked; 9:15 (16:15 UTC) survives.
    assert "2026-05-04T09:00:00-07:00" not in times
    assert "2026-05-04T09:15:00-07:00" in times


def test_find_available_slots_subtracts_administrative_blocks(mocker):
    # provider_availability writes blocks to a "{Provider}: Administrative" calendar.
    # The scheduler must subtract those, even though they have no allowed_note_types.
    _set_note_type_filter(mocker, [_good_nt()])
    clinic = SimpleNamespace(id="cal-c", dbid=10, title="Dr. Smith: Clinic", timezone=ZoneInfo("UTC"))
    admin = SimpleNamespace(id="cal-a", dbid=20, title="Dr. Smith: Administrative", timezone=ZoneInfo("UTC"))
    _set_calendar_filter(mocker, [clinic, admin])
    staff = SimpleNamespace(id="s1", dbid=1, full_name="Dr. Smith", active=True, roles=_roles("PROVIDER"))
    _set_staff_filter(mocker, [staff])
    avail = SimpleNamespace(
        starts_at=datetime.datetime(2026, 5, 4, 9, tzinfo=datetime.timezone.utc),
        ends_at=datetime.datetime(2026, 5, 4, 10, tzinfo=datetime.timezone.utc),
        recurrence=None,
        calendar_id=clinic.dbid,
    )
    block = SimpleNamespace(  # 9:15-9:30 block on the Administrative calendar
        starts_at=datetime.datetime(2026, 5, 4, 9, 15, tzinfo=datetime.timezone.utc),
        ends_at=datetime.datetime(2026, 5, 4, 9, 30, tzinfo=datetime.timezone.utc),
        recurrence=None,
        calendar_id=admin.dbid,
    )
    _set_event_filter(mocker, [avail, block])
    _set_appointment_filter(mocker, [])

    slots = _call_find_slots()
    times = [s["start_iso"] for s in slots]
    # 9:00-10:00 availability = four 15-min slots; the 9:15 block removes one.
    assert "2026-05-04T09:15:00+00:00" not in times
    assert len(slots) == 3


def test_block_intervals_for_calendar_expands_recurrence_to_absolute(mocker):
    # A weekly block expands per occurrence and localizes to absolute instants.
    block = SimpleNamespace(
        starts_at=datetime.datetime(2026, 5, 4, 13, tzinfo=datetime.timezone.utc),  # 9 AM EDT
        ends_at=datetime.datetime(2026, 5, 4, 14, tzinfo=datetime.timezone.utc),
        recurrence="RRULE:FREQ=WEEKLY;BYDAY=MO",
    )
    intervals = block_intervals_for_calendar(
        [block],
        window_start=_DEFAULT_WINDOW_START,
        window_end=_DEFAULT_WINDOW_END,
        timezone=ZoneInfo("America/New_York"),
    )
    assert len(intervals) == 1  # only Monday 2026-05-04 falls in the window
    start, end = intervals[0]
    # 9-10 wall-clock in NY round-trips to 13:00-14:00 UTC.
    assert start.astimezone(datetime.timezone.utc) == datetime.datetime(
        2026, 5, 4, 13, tzinfo=datetime.timezone.utc
    )
    assert end.astimezone(datetime.timezone.utc) == datetime.datetime(
        2026, 5, 4, 14, tzinfo=datetime.timezone.utc
    )


def test_find_available_slots_unions_calendars_in_different_timezones(mocker):
    # A telehealth provider with clinic calendars in two timezones is bookable
    # across the union of both, each interpreted in its OWN Calendar.timezone.
    _set_note_type_filter(mocker, [_good_nt()])
    cal_ny = SimpleNamespace(
        id="cal-ny", dbid=10, title="Dr. Smith: Clinic: East", timezone=ZoneInfo("America/New_York")
    )
    cal_la = SimpleNamespace(
        id="cal-la", dbid=11, title="Dr. Smith: Clinic: West", timezone=ZoneInfo("America/Los_Angeles")
    )
    _set_calendar_filter(mocker, [cal_ny, cal_la])
    staff = SimpleNamespace(id="s1", dbid=1, full_name="Dr. Smith", active=True, roles=_roles("PROVIDER"))
    _set_staff_filter(mocker, [staff])
    events = [
        # 9:00-10:00 local in each zone — different absolute instants.
        SimpleNamespace(  # 13:00-14:00 UTC == 9-10 EDT
            starts_at=datetime.datetime(2026, 5, 4, 13, tzinfo=datetime.timezone.utc),
            ends_at=datetime.datetime(2026, 5, 4, 14, tzinfo=datetime.timezone.utc),
            recurrence=None,
            calendar_id=cal_ny.dbid,
        ),
        SimpleNamespace(  # 16:00-17:00 UTC == 9-10 PDT
            starts_at=datetime.datetime(2026, 5, 4, 16, tzinfo=datetime.timezone.utc),
            ends_at=datetime.datetime(2026, 5, 4, 17, tzinfo=datetime.timezone.utc),
            recurrence=None,
            calendar_id=cal_la.dbid,
        ),
    ]
    _set_event_filter(mocker, events)
    _set_appointment_filter(mocker, [])

    slots = _call_find_slots()
    times = [s["start_iso"] for s in slots]
    # Each calendar's first slot reads 9:00 local but carries its own offset.
    assert "2026-05-04T09:00:00-04:00" in times  # New York
    assert "2026-05-04T09:00:00-07:00" in times  # Los Angeles
    # 4 + 4, NOT deduped (different absolute instants), sorted east-before-west.
    assert len(slots) == 8
    assert _slot_instant(slots[0]) < _slot_instant(slots[-1])


# ---- _calendar_timezone / _slot_instant -------------------------------------


def test_calendar_timezone_uses_the_calendar_field() -> None:
    cal = SimpleNamespace(timezone=ZoneInfo("America/New_York"))
    assert _calendar_timezone(cal, ZoneInfo("UTC")) == ZoneInfo("America/New_York")


def test_calendar_timezone_coerces_a_string_value() -> None:
    cal = SimpleNamespace(timezone="America/Los_Angeles")
    assert _calendar_timezone(cal, ZoneInfo("UTC")) == ZoneInfo("America/Los_Angeles")


def test_calendar_timezone_falls_back_when_missing_or_invalid() -> None:
    default = ZoneInfo("America/Chicago")
    assert _calendar_timezone(SimpleNamespace(timezone=None), default) == default
    assert _calendar_timezone(SimpleNamespace(timezone="Not/AZone"), default) == default
    assert _calendar_timezone(SimpleNamespace(), default) == default  # attribute absent


def test_slot_instant_compares_across_offsets() -> None:
    ny = {"start_iso": "2026-05-04T09:00:00-04:00"}  # 13:00 UTC
    la = {"start_iso": "2026-05-04T09:00:00-07:00"}  # 16:00 UTC
    same_instant_as_ny = {"start_iso": "2026-05-04T13:00:00+00:00"}
    assert _slot_instant(ny) < _slot_instant(la)
    assert _slot_instant(ny) == _slot_instant(same_instant_as_ny)
