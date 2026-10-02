"""Tests for multi-day all-day events expanding into one Canvas hold per covered day.

Canvas blocks a hold's date of service and nothing after it, so a single hold carrying a five-day
duration left days 2-5 of a provider's PTO bookable (PLUGIN-445). These cover the expansion itself
and the reconcile that keeps the per-day set matching the Google event as it is edited.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import arrow

from gcal_sync.inbound import InboundSync
from gcal_sync.inbound_holds import (
    ALL_DAY_DURATION_MINUTES,
    MAX_ALL_DAY_SPAN_DAYS,
    all_day_dates,
    build_hold_effect,
    hold_external_id,
    hold_title,
)

SECRETS = {"GOOGLE_SERVICE_ACCOUNT_JSON": '{"client_email": "svc@x.iam", "private_key": "KEY"}'}


# --- all_day_dates -------------------------------------------------------------------------------


def test_all_day_dates_spans_every_covered_day():
    # Google stores end.date exclusively: PTO 8/31 through 9/4 arrives as end.date 9/5.
    assert all_day_dates(
        {"start": {"date": "2026-08-31"}, "end": {"date": "2026-09-05"}}
    ) == [
        "2026-08-31",
        "2026-09-01",
        "2026-09-02",
        "2026-09-03",
        "2026-09-04",
    ]


def test_all_day_dates_single_day():
    assert all_day_dates(
        {"start": {"date": "2026-08-31"}, "end": {"date": "2026-09-01"}}
    ) == ["2026-08-31"]


def test_all_day_dates_without_end_is_one_day():
    assert all_day_dates({"start": {"date": "2026-08-31"}}) == ["2026-08-31"]


def test_all_day_dates_non_advancing_end_is_one_day():
    assert all_day_dates(
        {"start": {"date": "2026-08-31"}, "end": {"date": "2026-08-31"}}
    ) == ["2026-08-31"]


def test_all_day_dates_empty_for_timed_event():
    assert all_day_dates({"start": {"dateTime": "2026-08-31T09:00:00Z"}}) == []


def test_all_day_dates_empty_for_unparseable_date():
    assert all_day_dates({"start": {"date": "not-a-date"}}) == []


def test_all_day_dates_capped():
    dates = all_day_dates({"start": {"date": "2026-01-01"}, "end": {"date": "2027-01-01"}})
    assert len(dates) == MAX_ALL_DAY_SPAN_DAYS
    assert dates[0] == "2026-01-01"


# --- identifiers and titles ----------------------------------------------------------------------


def test_hold_external_id_suffixes_the_day():
    assert hold_external_id("g1", "2026-09-01") == "g1:2026-09-01"
    assert hold_external_id("g1") == "g1"


def test_hold_title_masks_private():
    assert hold_title({"visibility": "private", "summary": "Dad - Dr. Appt"}) == "Busy"
    assert hold_title({"summary": "PTO"}) == "PTO"
    assert hold_title({}) == "Busy"


# --- build_hold_effect for one day of an expansion -----------------------------------------------


def test_build_hold_effect_for_a_day_blocks_that_whole_date(mocker):
    mocker.patch("gcal_sync.inbound_holds.AppointmentIdentifier")
    se = mocker.patch("gcal_sync.inbound_holds.ScheduleEvent")
    event = {"id": "g1", "summary": "PTO", "start": {"date": "2026-08-31"}, "end": {"date": "2026-09-05"}}
    build_hold_effect(event, "nt-1", "14", "loc-1", date="2026-09-02")
    kwargs = se.call_args.kwargs
    assert kwargs["duration_minutes"] == ALL_DAY_DURATION_MINUTES
    assert arrow.get(kwargs["start_time"]).format("YYYY-MM-DD") == "2026-09-02"


def test_build_hold_effect_for_a_day_stamps_the_per_day_identifier(mocker):
    ident = mocker.patch("gcal_sync.inbound_holds.AppointmentIdentifier")
    mocker.patch("gcal_sync.inbound_holds.ScheduleEvent")
    event = {"id": "g1", "summary": "PTO", "start": {"date": "2026-08-31"}, "end": {"date": "2026-09-05"}}
    build_hold_effect(event, "nt-1", "14", "loc-1", date="2026-09-02")
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


def _inbound(mocker, secrets=None, live=None, ever_existed=False, mapping=None, pending=None):
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
    mocker.patch(
        "gcal_sync.inbound.build_hold_effect",
        side_effect=lambda event, nt, prov, loc, date=None: f"CREATE:{date}",
    )
    mocker.patch.object(
        inbound,
        "_day_hold_update_effect",
        side_effect=lambda canvas_id, event, date: f"UPDATE:{canvas_id}:{date}",
    )
    return inbound


def test_multi_day_pto_creates_one_hold_per_day(mocker):
    # The PLUGIN-445 repro: five days of PTO used to produce one hold and leave days 2-5 bookable.
    event, dates = _all_day_event(5)
    inbound = _inbound(mocker)
    stats = _stats()
    effects = inbound._apply("cal", event, stats)
    assert effects == [f"CREATE:{date}" for date in dates]
    assert stats["holds_created"] == 5


def test_single_day_all_day_event_creates_one_hold(mocker):
    event, dates = _all_day_event(1)
    inbound = _inbound(mocker)
    stats = _stats()
    effects = inbound._apply("cal", event, stats)
    assert effects == [f"CREATE:{dates[0]}"]
    assert stats["holds_created"] == 1


def test_existing_pre_expansion_hold_is_adopted_not_duplicated(mocker):
    # The hold that already exists on riviamind carries the BARE event id and covers day one. It
    # becomes day one's hold; only the uncovered days are created.
    event, dates = _all_day_event(5)
    inbound = _inbound(
        mocker,
        live={"g-pto": "appt-992668"},
        mapping=SimpleNamespace(google_event_id="g-pto", last_applied_hash=""),
    )
    stats = _stats()
    effects = inbound._apply("cal", event, stats)
    assert effects[0] == f"UPDATE:appt-992668:{dates[0]}"
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


def test_unchanged_hash_still_fills_a_missing_day(mocker):
    # The hash alone is not enough: the hold left behind by the old single-hold behavior matches on
    # content, and without the completeness check the missing days would never be created.
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
    assert effects == [f"CREATE:{dates[1]}", f"CREATE:{dates[2]}"]
    assert stats["holds_created"] == 2
    # Content did not move, so day one's existing hold is not needlessly re-saved.
    assert stats["holds_updated"] == 0


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


def test_create_in_flight_blocks_duplicate_expansion(mocker):
    event, _dates = _all_day_event(5)
    inbound = _inbound(
        mocker,
        pending=SimpleNamespace(created_at=datetime.now(timezone.utc)),
    )
    stats = _stats()
    assert inbound._apply("cal", event, stats) == []
    assert stats["holds_created"] == 0
    assert stats["ignored"] == 1


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


def test_day_hold_update_effect_moves_hold_to_that_whole_day(mocker):
    se = mocker.patch("gcal_sync.inbound.ScheduleEvent").return_value
    InboundSync._day_hold_update_effect("appt-1", {"summary": "PTO"}, "2026-09-02")
    assert se.duration_minutes == ALL_DAY_DURATION_MINUTES
    assert arrow.get(se.start_time).format("YYYY-MM-DD") == "2026-09-02"
    assert se.description == "PTO"


def test_day_hold_update_effect_masks_private_title(mocker):
    se = mocker.patch("gcal_sync.inbound.ScheduleEvent").return_value
    InboundSync._day_hold_update_effect(
        "appt-1", {"visibility": "private", "summary": "Dad - Dr. Appt"}, "2026-09-02"
    )
    assert se.description == "Busy"


def test_create_in_flight_without_marker_is_false(mocker):
    inbound = _bare_inbound(mocker)
    assert inbound._create_in_flight(None) is False


def test_unbuildable_day_is_skipped_without_losing_the_rest(mocker):
    # An incomplete import context makes build_hold_effect return None; the day is counted as
    # ignored and the other days still import.
    event, dates = _all_day_event(3)
    inbound = _inbound(mocker)
    mocker.patch(
        "gcal_sync.inbound.build_hold_effect",
        side_effect=lambda ev, nt, prov, loc, date=None: (
            None if date == dates[1] else f"CREATE:{date}"
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
