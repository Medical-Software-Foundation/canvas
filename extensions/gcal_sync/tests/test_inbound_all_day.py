"""Tests for multi-day events expanding into one Canvas hold per covered day.

Canvas blocks a hold's date of service and nothing after it, so a single hold carrying a five-day
duration left days 2-5 of a provider's PTO bookable. These cover the per-day split
(cut in the provider's time zone, for timed out-of-office spans as well as all-day events) and the
reconcile that keeps the per-day set matching the Google event as it is edited.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import arrow

from gcal_sync.google.client import CALENDAR_TIME_ZONE_KEY
from gcal_sync.inbound import InboundSync
from gcal_sync.inbound_holds import (
    MAX_SPAN_DAYS,
    DaySpan,
    build_hold_effect,
    event_day_spans,
    event_time_zone,
    hold_external_id,
    hold_title,
)

SECRETS = {"GOOGLE_SERVICE_ACCOUNT_JSON": '{"client_email": "svc@x.iam", "private_key": "KEY"}'}

FULL_DAY_MINUTES = 1439  # 00:00 to 23:59 local, so the hold never crosses into the next date


def _utc(value):
    return arrow.get(value).to("UTC").datetime


# --- event_time_zone -----------------------------------------------------------------------------


def test_time_zone_prefers_the_event_zone():
    event = {"start": {"timeZone": "America/Los_Angeles"}, CALENDAR_TIME_ZONE_KEY: "America/Chicago"}
    assert event_time_zone(event).key == "America/Los_Angeles"


def test_time_zone_falls_back_to_the_calendar_zone():
    # All-day events never name a zone; the calendar's zone rides along on the event.
    event = {"start": {"date": "2026-08-31"}, CALENDAR_TIME_ZONE_KEY: "America/Chicago"}
    assert event_time_zone(event).key == "America/Chicago"


def test_time_zone_defaults_to_the_clinic_zone():
    assert event_time_zone({"start": {"date": "2026-08-31"}}).key == "America/New_York"


def test_unknown_time_zone_falls_through_to_the_next_candidate():
    event = {"start": {"timeZone": "Not/AZone"}, CALENDAR_TIME_ZONE_KEY: "America/Chicago"}
    assert event_time_zone(event).key == "America/Chicago"


# --- event_day_spans: all-day events -------------------------------------------------------------


def test_all_day_event_covers_every_day_local_midnight_to_2359():
    # Google stores end.date exclusively: PTO 8/31 through 9/4 arrives as end.date 9/5. Each day
    # starts at local midnight (04:00 UTC in EDT), not UTC midnight (8 PM the evening before).
    spans = event_day_spans({"start": {"date": "2026-08-31"}, "end": {"date": "2026-09-05"}})
    assert [s.date for s in spans] == [
        "2026-08-31",
        "2026-09-01",
        "2026-09-02",
        "2026-09-03",
        "2026-09-04",
    ]
    assert spans[0].start == _utc("2026-08-31T04:00:00Z")
    assert {s.duration_minutes for s in spans} == {FULL_DAY_MINUTES}


def test_all_day_single_day():
    spans = event_day_spans({"start": {"date": "2026-08-31"}, "end": {"date": "2026-09-01"}})
    assert spans == [DaySpan("2026-08-31", _utc("2026-08-31T04:00:00Z"), FULL_DAY_MINUTES)]


def test_all_day_without_end_is_one_day():
    assert [s.date for s in event_day_spans({"start": {"date": "2026-08-31"}})] == ["2026-08-31"]


def test_all_day_non_advancing_end_is_one_day():
    spans = event_day_spans({"start": {"date": "2026-08-31"}, "end": {"date": "2026-08-31"}})
    assert [s.date for s in spans] == ["2026-08-31"]


def test_all_day_uses_the_calendar_zone():
    spans = event_day_spans(
        {"start": {"date": "2026-08-31"}, "end": {"date": "2026-09-01"}, CALENDAR_TIME_ZONE_KEY: "America/Chicago"}
    )
    assert spans[0].start == _utc("2026-08-31T05:00:00Z")


def test_all_day_on_a_dst_change_still_ends_at_2359_local():
    # 11/1/2026 is a 25-hour day in New York; the hold still runs 00:00 EDT to 23:59 EST.
    spans = event_day_spans({"start": {"date": "2026-11-01"}, "end": {"date": "2026-11-02"}})
    assert spans[0].start == _utc("2026-11-01T04:00:00Z")
    assert spans[0].duration_minutes == FULL_DAY_MINUTES + 60


def test_spring_forward_day_does_not_cross_into_the_next_date():
    # 3/8/2026 is a 23-hour day; a wall-clock duration would push the hold past midnight.
    spans = event_day_spans({"start": {"date": "2026-03-08"}, "end": {"date": "2026-03-09"}})
    end = arrow.get(spans[0].start).shift(minutes=spans[0].duration_minutes).to("America/New_York")
    assert end.format("YYYY-MM-DD HH:mm") == "2026-03-08 23:59"


def test_unparseable_event_has_no_spans():
    assert event_day_spans({"start": {"date": "not-a-date"}}) == []
    assert event_day_spans({"start": {}}) == []


def test_spans_are_capped():
    spans = event_day_spans({"start": {"date": "2026-01-01"}, "end": {"date": "2027-01-01"}})
    assert len(spans) == MAX_SPAN_DAYS
    assert spans[0].date == "2026-01-01"


# --- event_day_spans: timed events ---------------------------------------------------------------


def test_timed_out_of_office_span_splits_like_an_all_day_event():
    # How Google stores out-of-office PTO: a dateTime span from local midnight to local midnight
    # (04:00 UTC), not a start.date event.
    spans = event_day_spans(
        {
            "start": {"dateTime": "2026-08-31T00:00:00-04:00", "timeZone": "America/New_York"},
            "end": {"dateTime": "2026-09-05T00:00:00-04:00", "timeZone": "America/New_York"},
        }
    )
    assert len(spans) == 5
    assert spans == event_day_spans({"start": {"date": "2026-08-31"}, "end": {"date": "2026-09-05"}})


def test_timed_span_given_in_utc_is_still_cut_in_the_event_zone():
    spans = event_day_spans(
        {
            "start": {"dateTime": "2026-08-31T04:00:00Z", "timeZone": "America/New_York"},
            "end": {"dateTime": "2026-09-02T04:00:00Z", "timeZone": "America/New_York"},
        }
    )
    assert [s.date for s in spans] == ["2026-08-31", "2026-09-01"]


def test_timed_span_keeps_partial_first_and_last_days():
    # Friday 5 PM to Monday 9 AM: Friday evening, all of Saturday and Sunday, Monday morning.
    spans = event_day_spans(
        {
            "start": {"dateTime": "2026-09-04T17:00:00-04:00", "timeZone": "America/New_York"},
            "end": {"dateTime": "2026-09-07T09:00:00-04:00", "timeZone": "America/New_York"},
        }
    )
    assert [(s.date, s.duration_minutes) for s in spans] == [
        ("2026-09-04", 6 * 60 + 59),
        ("2026-09-05", FULL_DAY_MINUTES),
        ("2026-09-06", FULL_DAY_MINUTES),
        ("2026-09-07", 9 * 60),
    ]
    assert spans[0].start == _utc("2026-09-04T21:00:00Z")
    assert spans[3].start == _utc("2026-09-07T04:00:00Z")


def test_timed_same_day_event_is_one_span():
    spans = event_day_spans(
        {"start": {"dateTime": "2026-09-01T09:00:00-04:00"}, "end": {"dateTime": "2026-09-01T10:00:00-04:00"}}
    )
    assert spans == [DaySpan("2026-09-01", _utc("2026-09-01T13:00:00Z"), 60)]


def test_timed_event_ending_at_midnight_stays_on_its_own_date():
    spans = event_day_spans(
        {"start": {"dateTime": "2026-09-01T20:00:00-04:00"}, "end": {"dateTime": "2026-09-02T00:00:00-04:00"}}
    )
    assert [(s.date, s.duration_minutes) for s in spans] == [("2026-09-01", 3 * 60 + 59)]


def test_timed_event_without_zone_is_cut_in_the_clinic_zone():
    # 01:00 UTC on 9/2 is 9 PM on 9/1 in New York, so this is a one-day event there.
    spans = event_day_spans(
        {"start": {"dateTime": "2026-09-01T23:00:00Z"}, "end": {"dateTime": "2026-09-02T01:00:00Z"}}
    )
    assert [s.date for s in spans] == ["2026-09-01"]


# --- identifiers and titles ----------------------------------------------------------------------


def test_hold_external_id_suffixes_the_day():
    assert hold_external_id("g1", "2026-09-01") == "g1:2026-09-01"
    assert hold_external_id("g1") == "g1"


def test_hold_title_masks_private():
    assert hold_title({"visibility": "private", "summary": "Dad - Dr. Appt"}) == "Busy"
    assert hold_title({"summary": "PTO"}) == "PTO"
    assert hold_title({}) == "Busy"


# --- build_hold_effect for one day of an expansion -----------------------------------------------

_DAY = DaySpan("2026-09-02", _utc("2026-09-02T04:00:00Z"), FULL_DAY_MINUTES)


def test_build_hold_effect_for_a_day_uses_that_day_span(mocker):
    mocker.patch("gcal_sync.inbound_holds.AppointmentIdentifier")
    se = mocker.patch("gcal_sync.inbound_holds.ScheduleEvent")
    event = {"id": "g1", "summary": "PTO", "start": {"date": "2026-08-31"}, "end": {"date": "2026-09-05"}}
    build_hold_effect(event, "nt-1", "14", "loc-1", _DAY)
    kwargs = se.call_args.kwargs
    assert kwargs["start_time"] == _DAY.start
    assert kwargs["duration_minutes"] == FULL_DAY_MINUTES


def test_build_hold_effect_for_a_day_stamps_the_per_day_identifier(mocker):
    ident = mocker.patch("gcal_sync.inbound_holds.AppointmentIdentifier")
    mocker.patch("gcal_sync.inbound_holds.ScheduleEvent")
    event = {"id": "g1", "summary": "PTO", "start": {"date": "2026-08-31"}, "end": {"date": "2026-09-05"}}
    build_hold_effect(event, "nt-1", "14", "loc-1", _DAY)
    assert ident.call_args.kwargs["value"] == "g1:2026-09-02"


# --- reconcile through InboundSync ----------------------------------------------------------------


def _stats():
    return {
        "processed": 0,
        "echoes": 0,
        "reverted": 0,
        "holds_created": 0,
        "holds_updated": 0,
        "holds_unchanged": 0,
        "holds_removed": 0,
        "ignored": 0,
        "full_resync": False,
    }


def _all_day_event(days, event_id="g-pto", **extra):
    """An all-day event of ``days`` days starting a week out (inside the import window)."""
    start = arrow.utcnow().shift(days=7).floor("day")
    event = {
        "id": event_id,
        "status": "confirmed",
        "summary": "PTO",
        "start": {"date": start.format("YYYY-MM-DD")},
        "end": {"date": start.shift(days=days).format("YYYY-MM-DD")},
    }
    event.update(extra)
    dates = [start.shift(days=offset).format("YYYY-MM-DD") for offset in range(days)]
    return event, dates


def _timed_ooo_event(days, event_id="g-ooo"):
    """A timed out-of-office span covering ``days`` whole New York days, a week out."""
    first = arrow.now("America/New_York").shift(days=7).floor("day")
    event = {
        "id": event_id,
        "status": "confirmed",
        "summary": "Out of office",
        "start": {"dateTime": first.isoformat(), "timeZone": "America/New_York"},
        "end": {"dateTime": first.shift(days=days).isoformat(), "timeZone": "America/New_York"},
    }
    dates = [first.shift(days=offset).format("YYYY-MM-DD") for offset in range(days)]
    return event, dates


def _inbound(
    mocker,
    secrets=None,
    live=None,
    ever_existed=False,
    mapping=None,
    pending=None,
    in_flight=None,
    removed_by_sync=None,
):
    """An InboundSync with the DB-backed lookups mocked out."""
    merged = dict(SECRETS)
    merged.update(secrets or {"INGEST_ALL_DAY_EVENTS": "true"})
    inbound = InboundSync(merged, client_factory=lambda cal: object())
    mocker.patch.object(inbound._sync, "push")
    mocker.patch.object(inbound._sync, "remove")
    mocker.patch("gcal_sync.inbound.schedule_event_note_type_id", return_value="nt-1")
    mocker.patch("gcal_sync.inbound.provider_and_location", return_value=("14", "loc-1"))
    mocker.patch("gcal_sync.inbound.InboundEventMapping").objects.filter.return_value.first.return_value = mapping
    mocker.patch("gcal_sync.inbound.PendingHoldCreate").objects.filter.return_value.first.return_value = pending
    mocker.patch.object(inbound, "_live_holds_for_event", return_value=live or {})
    mocker.patch.object(inbound, "_external_value_exists", return_value=ever_existed)
    mocker.patch.object(inbound, "_days_in_flight", return_value=set(in_flight or ()))
    mocker.patch.object(
        inbound, "_days_removed_by_sync", return_value=set(removed_by_sync or ())
    )
    mocker.patch.object(inbound, "_record_day_changes")
    mocker.patch(
        "gcal_sync.inbound.build_hold_effect",
        side_effect=lambda event, nt, prov, loc, day=None: f"CREATE:{day.date if day else 'single'}",
    )
    mocker.patch.object(
        inbound,
        "_day_hold_update_effect",
        side_effect=lambda canvas_id, event, day: f"UPDATE:{canvas_id}:{day.date}",
    )
    return inbound


def test_multi_day_pto_creates_one_hold_per_day(mocker):
    # The original repro: five days of PTO used to produce one hold and leave days 2-5 bookable.
    event, dates = _all_day_event(5)
    inbound = _inbound(mocker)
    stats = _stats()
    effects = inbound._apply("cal", event, stats)
    assert effects == [f"CREATE:{date}" for date in dates]
    assert stats["holds_created"] == 5


def test_timed_out_of_office_pto_creates_one_hold_per_day(mocker):
    # Out-of-office PTO arrives as a timed span, not as an all-day event.
    event, dates = _timed_ooo_event(5)
    inbound = _inbound(mocker)
    stats = _stats()
    effects = inbound._apply("cal", event, stats)
    assert effects == [f"CREATE:{date}" for date in dates]
    assert stats["holds_created"] == 5


def test_timed_multi_day_span_is_imported_even_with_all_day_ingest_off(mocker):
    # The all-day toggle is about start.date events (birthdays, "Home"); a timed span was always
    # imported, and turning it into per-day holds must not start dropping it.
    event, dates = _timed_ooo_event(3)
    inbound = _inbound(mocker, secrets={"INGEST_ALL_DAY_EVENTS": "false"})
    stats = _stats()
    assert inbound._apply("cal", event, stats) == [f"CREATE:{date}" for date in dates]


def test_single_day_timed_event_without_day_holds_takes_the_single_hold_path(mocker):
    inbound = _inbound(mocker)
    reconcile = mocker.patch.object(inbound, "_reconcile_day_holds")
    mocker.patch.object(inbound, "_canvas_id_for_google_event", return_value=None)
    mocker.patch.object(inbound, "_external_hold_exists", return_value=False)
    start = arrow.now("America/New_York").shift(days=7).replace(hour=9, minute=0, second=0, microsecond=0)
    event = {
        "id": "g-mtg",
        "status": "confirmed",
        "summary": "Meeting",
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": start.shift(hours=1).isoformat()},
    }
    inbound._apply("cal", event, _stats())
    reconcile.assert_not_called()


def test_event_shrunk_to_one_timed_day_clears_its_other_day_holds(mocker):
    # Review case: all-day PTO switched to a timed event on its first day. The per-day
    # holds for the days it no longer covers must go, not linger beside a new bare-id hold.
    _event, dates = _all_day_event(3, event_id="g-pto")
    first = arrow.get(dates[0]).replace(tzinfo="America/New_York").replace(hour=10)
    event = {
        "id": "g-pto",
        "status": "confirmed",
        "summary": "PTO",
        "start": {"dateTime": first.isoformat()},
        "end": {"dateTime": first.shift(hours=2).isoformat()},
    }
    inbound = _inbound(
        mocker,
        live={f"g-pto:{date}": f"appt-{i}" for i, date in enumerate(dates)},
        mapping=SimpleNamespace(google_event_id="g-pto", last_applied_hash=""),
    )
    mocker.patch.object(inbound, "_has_day_holds", return_value=True)
    se = mocker.patch("gcal_sync.inbound.ScheduleEvent")
    stats = _stats()
    effects = inbound._apply("cal", event, stats)
    assert effects[0] == f"UPDATE:appt-0:{dates[0]}"
    assert [c.kwargs for c in se.call_args_list] == [{"instance_id": "appt-1"}, {"instance_id": "appt-2"}]
    assert stats["holds_removed"] == 2
    assert stats["holds_created"] == 0


def test_has_day_holds_ignores_a_bare_id_hold(mocker):
    inbound = _bare_inbound(mocker)
    mocker.patch.object(inbound, "_live_holds_for_event", return_value={"g1": "appt-1"})
    assert inbound._has_day_holds("g1", "p1") is False
    mocker.patch.object(inbound, "_live_holds_for_event", return_value={"g1:2026-09-01": "appt-2"})
    assert inbound._has_day_holds("g1", "p1") is True
    assert inbound._has_day_holds("g1", None) is False


def test_single_day_all_day_event_creates_one_hold(mocker):
    event, dates = _all_day_event(1)
    inbound = _inbound(mocker)
    stats = _stats()
    effects = inbound._apply("cal", event, stats)
    assert effects == [f"CREATE:{dates[0]}"]
    assert stats["holds_created"] == 1


def test_existing_pre_expansion_hold_is_adopted_not_duplicated(mocker):
    # A hold imported before per-day expansion carries the BARE event id and covers day one. It
    # becomes day one's hold; only the uncovered days are created.
    event, dates = _all_day_event(5)
    inbound = _inbound(
        mocker,
        live={"g-pto": "appt-old"},
        mapping=SimpleNamespace(google_event_id="g-pto", last_applied_hash=""),
    )
    stats = _stats()
    effects = inbound._apply("cal", event, stats)
    assert effects[0] == f"UPDATE:appt-old:{dates[0]}"
    assert effects[1:] == [f"CREATE:{date}" for date in dates[1:]]
    assert stats["holds_created"] == 4
    assert stats["holds_updated"] == 1


def test_shortened_event_removes_the_days_it_no_longer_covers(mocker):
    event, dates = _all_day_event(2)
    stale_day = arrow.get(dates[-1]).shift(days=1).format("YYYY-MM-DD")
    inbound = _inbound(
        mocker,
        live={
            f"g-pto:{dates[0]}": "appt-1",
            f"g-pto:{dates[1]}": "appt-2",
            f"g-pto:{stale_day}": "appt-3",
        },
        mapping=SimpleNamespace(google_event_id="g-pto", last_applied_hash=""),
    )
    se = mocker.patch("gcal_sync.inbound.ScheduleEvent")
    stats = _stats()
    inbound._apply("cal", event, stats)
    se.assert_called_once_with(instance_id="appt-3")
    assert stats["holds_removed"] == 1
    assert stats["holds_created"] == 0


def test_unchanged_complete_set_is_a_no_op(mocker):
    event, dates = _all_day_event(3)
    from gcal_sync.google.event_builder import google_event_content_hash

    inbound = _inbound(
        mocker,
        live={f"g-pto:{date}": f"appt-{i}" for i, date in enumerate(dates)},
        mapping=SimpleNamespace(
            google_event_id="g-pto", last_applied_hash=google_event_content_hash(event)
        ),
    )
    stats = _stats()
    assert inbound._apply("cal", event, stats) == []
    assert stats["holds_unchanged"] == 1


def test_unchanged_hash_still_splits_a_pre_expansion_hold(mocker):
    # The hash alone is not enough: the hold left behind by the old single-hold behavior matches on
    # content. Without the completeness check the missing days would never be created, and without
    # reshaping the adopted hold it would keep its multi-day duration beside the new per-day holds.
    event, dates = _all_day_event(3)
    from gcal_sync.google.event_builder import google_event_content_hash

    inbound = _inbound(
        mocker,
        live={"g-pto": "appt-1"},
        mapping=SimpleNamespace(
            google_event_id="g-pto", last_applied_hash=google_event_content_hash(event)
        ),
    )
    stats = _stats()
    effects = inbound._apply("cal", event, stats)
    assert effects == [f"UPDATE:appt-1:{dates[0]}", f"CREATE:{dates[1]}", f"CREATE:{dates[2]}"]
    assert stats["holds_created"] == 2
    assert stats["holds_updated"] == 1


def test_all_day_ingest_off_creates_nothing(mocker):
    event, _dates = _all_day_event(5)
    inbound = _inbound(mocker, secrets={"INGEST_ALL_DAY_EVENTS": "false"})
    stats = _stats()
    assert inbound._apply("cal", event, stats) == []
    assert stats["holds_created"] == 0
    assert stats["ignored"] == 1


def test_private_all_day_event_not_ingested_when_disabled(mocker):
    event, _dates = _all_day_event(5, visibility="private")
    inbound = _inbound(
        mocker,
        secrets={"INGEST_ALL_DAY_EVENTS": "true", "INGEST_PRIVATE_EVENTS": "false"},
    )
    stats = _stats()
    assert inbound._apply("cal", event, stats) == []
    assert stats["holds_created"] == 0


def test_days_still_in_flight_are_not_created_twice(mocker):
    # A webhook re-delivered while the days' creates are still applying must not mint second holds.
    event, dates = _all_day_event(5)
    inbound = _inbound(mocker, in_flight=dates)
    stats = _stats()
    assert inbound._apply("cal", event, stats) == []
    assert stats["holds_created"] == 0
    assert stats["ignored"] == 1


def test_extension_soon_after_import_creates_the_added_days(mocker):
    # Found testing against a real calendar: PTO extended minutes after it was first imported. The marker
    # covered the whole event, so the pass was skipped and the added days stayed bookable for 30
    # minutes, and on the webhook path until the event changed again. Only the days whose own create
    # is in flight are held back now, and those are already live here.
    event, dates = _all_day_event(5)
    inbound = _inbound(
        mocker,
        live={f"g-pto:{date}": f"appt-{i}" for i, date in enumerate(dates[:3])},
        mapping=SimpleNamespace(google_event_id="g-pto", last_applied_hash=""),
        in_flight=dates[:3],
    )
    stats = _stats()
    effects = inbound._apply("cal", event, stats)
    assert effects == [
        f"UPDATE:appt-0:{dates[0]}",
        f"UPDATE:appt-1:{dates[1]}",
        f"UPDATE:appt-2:{dates[2]}",
        f"CREATE:{dates[3]}",
        f"CREATE:{dates[4]}",
    ]
    assert stats["holds_created"] == 2


def test_bare_event_marker_holds_back_only_the_first_day(mocker):
    # The single-hold path marks the bare event id. That hold becomes the first day's hold once it
    # applies, so the other days are created now rather than 30 minutes later.
    event, dates = _all_day_event(3)
    inbound = _inbound(
        mocker,
        pending=SimpleNamespace(created_at=datetime.now(timezone.utc)),
    )
    stats = _stats()
    assert inbound._apply("cal", event, stats) == [f"CREATE:{date}" for date in dates[1:]]


def test_updates_and_removals_go_through_while_a_day_is_in_flight(mocker):
    event, dates = _all_day_event(3)
    stale_day = arrow.get(dates[-1]).shift(days=1).format("YYYY-MM-DD")
    inbound = _inbound(
        mocker,
        live={f"g-pto:{dates[0]}": "appt-0", f"g-pto:{stale_day}": "appt-9"},
        mapping=SimpleNamespace(google_event_id="g-pto", last_applied_hash=""),
        in_flight=[dates[1]],
    )
    se = mocker.patch("gcal_sync.inbound.ScheduleEvent")
    stats = _stats()
    effects = inbound._apply("cal", event, stats)
    assert effects[:2] == [f"UPDATE:appt-0:{dates[0]}", f"CREATE:{dates[2]}"]
    se.assert_called_once_with(instance_id="appt-9")
    assert stats["holds_removed"] == 1


def test_day_the_sync_removed_is_held_again_when_the_event_covers_it_again(mocker):
    # Found testing against a real calendar: PTO shortened (the sync cancelled the dropped days) and then
    # extended back over them. The per-day convergence guard saw that a hold had existed and left
    # the days bookable until an admin Re-import.
    event, dates = _all_day_event(5)
    inbound = _inbound(
        mocker,
        live={f"g-pto:{date}": f"appt-{i}" for i, date in enumerate(dates[:3])},
        mapping=SimpleNamespace(google_event_id="g-pto", last_applied_hash=""),
        ever_existed=True,
        removed_by_sync=dates[3:],
    )
    stats = _stats()
    effects = inbound._apply("cal", event, stats)
    assert effects[3:] == [f"CREATE:{dates[3]}", f"CREATE:{dates[4]}"]
    assert stats["holds_created"] == 2


def test_out_of_band_cancel_still_stays_cancelled_beside_a_sync_removed_day(mocker):
    # Only the sync's own removals are re-held; a day cancelled any other way keeps the guard.
    event, dates = _all_day_event(5)
    inbound = _inbound(
        mocker,
        live={f"g-pto:{date}": f"appt-{i}" for i, date in enumerate(dates[:3])},
        mapping=SimpleNamespace(google_event_id="g-pto", last_applied_hash=""),
        ever_existed=True,
        removed_by_sync=[dates[4]],
    )
    stats = _stats()
    effects = inbound._apply("cal", event, stats)
    assert effects[3:] == [f"CREATE:{dates[4]}"]


def test_pass_records_its_created_and_uncovered_days(mocker):
    event, dates = _all_day_event(3)
    stale_day = arrow.get(dates[-1]).shift(days=1).format("YYYY-MM-DD")
    inbound = _inbound(
        mocker,
        live={f"g-pto:{dates[0]}": "appt-0", f"g-pto:{stale_day}": "appt-9"},
        mapping=SimpleNamespace(google_event_id="g-pto", last_applied_hash=""),
    )
    mocker.patch("gcal_sync.inbound.ScheduleEvent")
    inbound._apply("cal", event, _stats())
    inbound._record_day_changes.assert_called_once_with(
        "cal", "g-pto", dates[1:], [stale_day]
    )


def test_duplicate_hold_on_a_covered_day_is_not_recorded_as_uncovered(mocker):
    # A pre-expansion hold adopted as day one plus that day's per-day hold: the extra one goes, but
    # the day is still covered, so it must not earn a "removed by the sync" pass.
    event, dates = _all_day_event(2)
    inbound = _inbound(
        mocker,
        live={"g-pto": "appt-old", f"g-pto:{dates[0]}": "appt-dup"},
        mapping=SimpleNamespace(google_event_id="g-pto", last_applied_hash=""),
    )
    mocker.patch("gcal_sync.inbound.ScheduleEvent")
    inbound._apply("cal", event, _stats())
    assert inbound._record_day_changes.call_args.args[3] == []


def test_dry_run_records_nothing(mocker):
    event, _dates = _all_day_event(3)
    inbound = _inbound(mocker)
    inbound._apply("cal", event, _stats(), dry_run=True)
    inbound._record_day_changes.assert_not_called()


def test_orphaned_pending_marker_past_grace_recreates(mocker):
    event, dates = _all_day_event(2)
    inbound = _inbound(
        mocker,
        pending=SimpleNamespace(created_at=datetime.now(timezone.utc) - timedelta(hours=2)),
    )
    stats = _stats()
    effects = inbound._apply("cal", event, stats)
    assert effects == [f"CREATE:{dates[0]}", f"CREATE:{dates[1]}"]


def test_day_whose_hold_was_cancelled_is_not_recreated(mocker):
    # Convergence guard, per day: a hold cancelled out-of-band stays cancelled.
    event, _dates = _all_day_event(3)
    inbound = _inbound(mocker, ever_existed=True)
    stats = _stats()
    assert inbound._apply("cal", event, stats) == []
    assert stats["holds_created"] == 0


def test_force_rebuild_ignores_the_per_day_convergence_guard(mocker):
    event, dates = _all_day_event(3)
    inbound = _inbound(mocker, ever_existed=True)
    stats = _stats()
    effects = inbound._apply("cal", event, stats, force_rebuild=True)
    assert effects == [f"CREATE:{date}" for date in dates]


# --- the DB-backed lookups themselves -------------------------------------------------------------


def _bare_inbound(mocker):
    inbound = InboundSync(SECRETS, client_factory=lambda cal: object())
    mocker.patch.object(inbound._sync, "push")
    mocker.patch.object(inbound._sync, "remove")
    return inbound


def test_live_holds_for_event_keeps_only_this_event(mocker):
    # The DB filter is a prefix match, so a longer event id starting with this one comes back too.
    # The separator check is what excludes it.
    aei = mocker.patch("gcal_sync.inbound.AppointmentExternalIdentifier")
    aei.objects.filter.return_value.exclude.return_value.values_list.return_value = [
        ("g1", "appt-1"),
        ("g1:2026-09-01", "appt-2"),
        ("g1extra", "appt-3"),
        ("g1extra:2026-09-01", "appt-4"),
    ]
    result = InboundSync._live_holds_for_event("g1", "p1")
    assert result == {"g1": "appt-1", "g1:2026-09-01": "appt-2"}


def test_external_value_exists(mocker):
    aei = mocker.patch("gcal_sync.inbound.AppointmentExternalIdentifier")
    aei.objects.filter.return_value.exists.return_value = True
    assert InboundSync._external_value_exists("g1:2026-09-01", "p1") is True
    assert aei.objects.filter.call_args.kwargs["value"] == "g1:2026-09-01"


def test_day_hold_update_effect_moves_hold_to_that_day_span(mocker):
    # Updates cut the day the same way creates do, so an edit can't move a hold back to UTC midnight.
    se = mocker.patch("gcal_sync.inbound.ScheduleEvent").return_value
    InboundSync._day_hold_update_effect("appt-1", {"summary": "PTO"}, _DAY)
    assert se.start_time == _DAY.start
    assert se.duration_minutes == FULL_DAY_MINUTES
    assert se.description == "PTO"


def test_day_hold_update_effect_masks_private_title(mocker):
    se = mocker.patch("gcal_sync.inbound.ScheduleEvent").return_value
    InboundSync._day_hold_update_effect(
        "appt-1", {"visibility": "private", "summary": "Dad - Dr. Appt"}, _DAY
    )
    assert se.description == "Busy"


def test_create_in_flight_without_marker_is_false(mocker):
    inbound = _bare_inbound(mocker)
    assert inbound._create_in_flight(None) is False


def test_days_in_flight_reads_fresh_per_day_markers_for_this_calendar(mocker):
    inbound = _bare_inbound(mocker)
    phc = mocker.patch("gcal_sync.inbound.PendingHoldCreate")
    now = datetime.now(timezone.utc)
    phc.objects.filter.return_value.values_list.return_value = [
        ("g1:2026-09-01", now),
        ("g1:2026-09-02", now - timedelta(hours=2)),  # past the grace window
        ("g1:2026-09-03", None),  # unaged reads as fresh
    ]
    result = inbound._days_in_flight("cal", "g1", ["2026-09-01", "2026-09-02", "2026-09-03"])
    assert result == {"2026-09-01", "2026-09-03"}
    kwargs = phc.objects.filter.call_args.kwargs
    assert kwargs["google_calendar_id"] == "cal"
    assert sorted(kwargs["google_event_id__in"]) == [
        "g1:2026-09-01",
        "g1:2026-09-02",
        "g1:2026-09-03",
    ]


def test_days_removed_by_sync_reads_this_calendars_records(mocker):
    rdh = mocker.patch("gcal_sync.inbound.RemovedDayHold")
    rdh.objects.filter.return_value.values_list.return_value = ["g1:2026-09-02"]
    result = InboundSync._days_removed_by_sync("cal", "g1", ["2026-09-01", "2026-09-02"])
    assert result == {"2026-09-02"}
    assert rdh.objects.filter.call_args.kwargs["google_calendar_id"] == "cal"


def test_record_day_changes_marks_created_and_removed_days(mocker):
    phc = mocker.patch("gcal_sync.inbound.PendingHoldCreate")
    rdh = mocker.patch("gcal_sync.inbound.RemovedDayHold")
    InboundSync._record_day_changes("cal", "g1", ["2026-09-01"], ["2026-09-05"])
    # The created day gets its own in-flight marker and loses any removed-day record.
    assert phc.objects.update_or_create.call_args.kwargs["google_event_id"] == "g1:2026-09-01"
    assert phc.objects.update_or_create.call_args.kwargs["google_calendar_id"] == "cal"
    assert rdh.objects.filter.call_args.kwargs["google_event_id__in"] == ["g1:2026-09-01"]
    rdh.objects.filter.return_value.delete.assert_called_once()
    # The uncovered day is recorded as removed by the sync and its in-flight marker dropped.
    rdh.objects.get_or_create.assert_called_once_with(
        google_event_id="g1:2026-09-05", google_calendar_id="cal"
    )
    assert phc.objects.filter.call_args.kwargs["google_event_id__in"] == ["g1:2026-09-05"]
    phc.objects.filter.return_value.delete.assert_called_once()


def test_record_day_changes_with_nothing_to_record_touches_nothing(mocker):
    phc = mocker.patch("gcal_sync.inbound.PendingHoldCreate")
    rdh = mocker.patch("gcal_sync.inbound.RemovedDayHold")
    InboundSync._record_day_changes("cal", "g1", [], [])
    assert phc.mock_calls == []
    assert rdh.mock_calls == []


def test_cancelled_event_clears_its_per_day_markers_and_records(mocker):
    _event, dates = _all_day_event(2)
    inbound = _inbound(mocker, live={f"g-pto:{date}": f"appt-{i}" for i, date in enumerate(dates)})
    mocker.patch("gcal_sync.inbound.ScheduleEvent")
    phc = mocker.patch("gcal_sync.inbound.PendingHoldCreate")
    rdh = mocker.patch("gcal_sync.inbound.RemovedDayHold")
    inbound._apply("cal", {"id": "g-pto", "status": "cancelled"}, _stats())
    for model in (phc, rdh):
        model.objects.filter.assert_any_call(
            google_calendar_id="cal", google_event_id__startswith="g-pto:"
        )


def test_unbuildable_day_is_skipped_without_losing_the_rest(mocker):
    # An incomplete import context makes build_hold_effect return None; the day is counted as
    # ignored and the other days still import.
    event, dates = _all_day_event(3)
    inbound = _inbound(mocker)
    mocker.patch(
        "gcal_sync.inbound.build_hold_effect",
        side_effect=lambda ev, nt, prov, loc, day=None: (
            None if day.date == dates[1] else f"CREATE:{day.date}"
        ),
    )
    stats = _stats()
    effects = inbound._apply("cal", event, stats)
    assert effects == [f"CREATE:{dates[0]}", f"CREATE:{dates[2]}"]
    assert stats["holds_created"] == 2
    assert stats["ignored"] == 1


def test_unmapped_calendar_is_ignored_once(mocker):
    event, _dates = _all_day_event(5)
    inbound = _inbound(mocker)
    mocker.patch("gcal_sync.inbound.provider_and_location", return_value=None)
    inbound._import_ctx = None
    stats = _stats()
    assert inbound._apply("cal", event, stats) == []
    assert stats["ignored"] == 1


def test_missing_note_type_is_reported_once_not_per_day(mocker):
    event, _dates = _all_day_event(5)
    inbound = _inbound(mocker)
    mocker.patch("gcal_sync.inbound.schedule_event_note_type_id", return_value=None)
    inbound._import_ctx = None
    stats = _stats()
    assert inbound._apply("cal", event, stats) == []
    assert stats["ignored"] == 1
