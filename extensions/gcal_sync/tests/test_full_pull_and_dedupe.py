"""Tests for the periodic full pull and the duplicate-hold guards for shared events.

A delta pull only returns what Google reports as changed, so an event a delta never delivered stayed
missing until someone re-imported by hand; the periodic full pull re-checks each calendar's window
about daily. Two concurrent runs for the same calendar could both pass the old check-then-write
in-flight marker and each create a hold; the claim is now atomic, and existing duplicates are
removed on the next pass. Google is mocked throughout; no credentials are needed.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from django.db import IntegrityError
from gcal_sync import reconcile
from gcal_sync.inbound import InboundSync

SECRETS = {
    "GOOGLE_SERVICE_ACCOUNT_JSON": '{"client_email": "svc@x.iam", "private_key": "KEY"}'
}
NOW = datetime.now(UTC)


def _inbound(mocker, client=None):
    inbound = InboundSync(SECRETS, client_factory=lambda cal: client or object())
    mocker.patch.object(inbound._sync, "push")
    mocker.patch.object(inbound._sync, "remove")
    mocker.patch("gcal_sync.inbound.RemovedDayHold")
    return inbound


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
        "capped": False,
    }


# --- atomic create claim --------------------------------------------------------------------------


def test_claim_without_marker_inserts_one(mocker):
    phc = mocker.patch("gcal_sync.inbound.PendingHoldCreate")
    assert _inbound(mocker)._claim_create("cal", "g1", None) is True
    kwargs = phc.objects.create.call_args.kwargs
    assert (kwargs["google_event_id"], kwargs["google_calendar_id"]) == ("g1", "cal")


def test_claim_loses_when_a_concurrent_run_inserted_first(mocker):
    phc = mocker.patch("gcal_sync.inbound.PendingHoldCreate")
    phc.objects.create.side_effect = IntegrityError("uq_pending_hold")
    assert _inbound(mocker)._claim_create("cal", "g1", None) is False


def test_claim_refuses_a_fresh_marker_without_writing(mocker):
    phc = mocker.patch("gcal_sync.inbound.PendingHoldCreate")
    fresh = SimpleNamespace(created_at=NOW)
    assert _inbound(mocker)._claim_create("cal", "g1", fresh) is False
    phc.objects.create.assert_not_called()
    phc.objects.filter.assert_not_called()


def test_stale_marker_goes_to_exactly_one_runner(mocker):
    phc = mocker.patch("gcal_sync.inbound.PendingHoldCreate")
    stale = SimpleNamespace(created_at=NOW - timedelta(hours=2))
    inbound = _inbound(mocker)
    phc.objects.filter.return_value.update.return_value = 1
    assert inbound._claim_create("cal", "g1", stale) is True
    # The refresh is conditional on the created_at this run read, so a racing run matches 0 rows.
    assert phc.objects.filter.call_args.kwargs["created_at"] == stale.created_at
    phc.objects.filter.return_value.update.return_value = 0
    assert inbound._claim_create("cal", "g1", stale) is False


def test_claim_day_create_reads_that_days_marker(mocker):
    phc = mocker.patch("gcal_sync.inbound.PendingHoldCreate")
    phc.objects.filter.return_value.first.return_value = SimpleNamespace(created_at=NOW)
    assert _inbound(mocker)._claim_day_create("cal", "g1:2026-09-01") is False
    assert phc.objects.filter.call_args.kwargs["google_event_id"] == "g1:2026-09-01"


def test_single_hold_create_lost_claim_returns_nothing_and_writes_no_mapping(mocker):
    iem = mocker.patch("gcal_sync.inbound.InboundEventMapping")
    iem.objects.filter.return_value.first.return_value = None
    phc = mocker.patch("gcal_sync.inbound.PendingHoldCreate")
    phc.objects.filter.return_value.first.return_value = None
    phc.objects.create.side_effect = IntegrityError("uq_pending_hold")
    mocker.patch("gcal_sync.inbound.schedule_event_note_type_id", return_value="nt-1")
    mocker.patch(
        "gcal_sync.inbound.provider_and_location", return_value=("14", "loc-1")
    )
    mocker.patch("gcal_sync.inbound.build_hold_effect", return_value="HOLD_EFFECT")
    inbound = _inbound(mocker)
    mocker.patch.object(inbound, "_canvas_id_for_google_event", return_value=None)
    mocker.patch.object(inbound, "_external_hold_exists", return_value=False)
    stats = _stats()
    assert inbound._apply("cal", {"id": "g1", "status": "confirmed"}, stats) == []
    assert stats["holds_created"] == 0
    iem.objects.update_or_create.assert_not_called()


# --- duplicate live holds -------------------------------------------------------------------------


def test_all_live_hold_ids_keeps_same_value_duplicates_and_drops_other_events(mocker):
    aei = mocker.patch("gcal_sync.inbound.AppointmentExternalIdentifier")
    aei.objects.filter.return_value.exclude.return_value.values_list.return_value = [
        ("g1", "appt-2"),
        ("g1", "appt-1"),
        ("g1:2026-09-01", "appt-3"),
        ("g1extra", "appt-9"),
    ]
    assert InboundSync._all_live_hold_ids("g1", "p1") == ["appt-1", "appt-2", "appt-3"]
    assert aei.objects.filter.call_args.kwargs["appointment__provider__id"] == "p1"


def _known_event(mocker, last_hash):
    iem = mocker.patch("gcal_sync.inbound.InboundEventMapping")
    iem.objects.filter.return_value.first.return_value = SimpleNamespace(
        google_event_id="g1", last_applied_hash=last_hash
    )
    mocker.patch(
        "gcal_sync.inbound.PendingHoldCreate"
    ).objects.filter.return_value.first.return_value = None
    mocker.patch("gcal_sync.inbound.schedule_event_note_type_id", return_value="nt-1")
    mocker.patch(
        "gcal_sync.inbound.provider_and_location", return_value=("14", "loc-1")
    )
    se = mocker.patch("gcal_sync.inbound.ScheduleEvent")
    se.return_value.delete.side_effect = lambda: (
        f"DELETE:{se.call_args.kwargs['instance_id']}"
    )
    inbound = _inbound(mocker)
    mocker.patch.object(inbound, "_canvas_id_for_google_event", return_value="appt-1")
    mocker.patch.object(
        inbound, "_all_live_hold_ids", return_value=["appt-1", "appt-2"]
    )
    mocker.patch.object(inbound, "_hold_update_effect", return_value="UPDATE:appt-1")
    return inbound


def test_unchanged_event_with_a_duplicate_hold_removes_only_the_extra(mocker):
    event = {"id": "g1", "status": "confirmed", "summary": "Standup"}
    mocker.patch("gcal_sync.inbound.google_event_content_hash", return_value="h1")
    inbound = _known_event(mocker, last_hash="h1")
    stats = _stats()
    assert inbound._apply("cal", event, stats) == ["DELETE:appt-2"]
    assert stats["holds_removed"] == 1
    assert stats["holds_unchanged"] == 1


def test_changed_event_with_a_duplicate_hold_updates_one_and_removes_the_other(mocker):
    event = {"id": "g1", "status": "confirmed", "summary": "Standup"}
    mocker.patch("gcal_sync.inbound.google_event_content_hash", return_value="h2")
    inbound = _known_event(mocker, last_hash="h1")
    stats = _stats()
    assert inbound._apply("cal", event, stats) == ["UPDATE:appt-1", "DELETE:appt-2"]
    assert stats["holds_updated"] == 1
    assert stats["holds_removed"] == 1


# --- process_calendar(full_pull=True) -------------------------------------------------------------


def _state(mocker, sync_token="tok", needs=False):
    state = SimpleNamespace(
        sync_token=sync_token,
        needs_full_resync=needs,
        last_full_pull_at=None,
        save=mocker.Mock(),
    )
    css = mocker.patch("gcal_sync.inbound.CalendarSyncState")
    css.objects.get_or_create.return_value = (state, False)
    return state


def test_full_pull_ignores_a_valid_token_and_stamps_the_pull(mocker):
    state = _state(mocker)
    client = SimpleNamespace(list_event_deltas=mocker.Mock(return_value=([], "newtok")))
    inbound = _inbound(mocker, client)
    inbound.process_calendar("c1", full_pull=True)
    kwargs = client.list_event_deltas.call_args.kwargs
    assert kwargs["sync_token"] == ""
    assert kwargs["time_min"] and kwargs["time_max"]
    assert state.sync_token == "newtok"
    assert state.last_full_pull_at is not None


def test_delta_pull_does_not_stamp_a_full_pull(mocker):
    state = _state(mocker)
    client = SimpleNamespace(list_event_deltas=mocker.Mock(return_value=([], "newtok")))
    _inbound(mocker, client).process_calendar("c1")
    assert client.list_event_deltas.call_args.kwargs["sync_token"] == "tok"
    assert state.last_full_pull_at is None


def test_full_pull_keeps_the_convergence_guard(mocker):
    state = _state(mocker)
    client = SimpleNamespace(
        list_event_deltas=mocker.Mock(return_value=([{"id": "g1"}], "t2"))
    )
    inbound = _inbound(mocker, client)
    apply = mocker.patch.object(inbound, "_apply", return_value=[])
    inbound.process_calendar("c1", full_pull=True)
    # Positional force_rebuild stays False: a periodic pull never revives a cancelled hold.
    assert apply.call_args.args[3] is False
    assert state.needs_full_resync is False


# --- periodic_full_pull ---------------------------------------------------------------------------


def _sync_state(cal, last=None, token="tok", needs=False):
    return SimpleNamespace(
        google_calendar_id=cal,
        sync_token=token,
        needs_full_resync=needs,
        last_full_pull_at=last,
    )


def _fleet(mocker, states, busy=()):
    scm = mocker.patch("gcal_sync.reconcile.StaffCalendarMapping")
    scm.objects.filter.return_value.values_list.return_value = [
        s.google_calendar_id for s in states
    ]
    css = mocker.patch("gcal_sync.reconcile.CalendarSyncState")
    stamp = mocker.Mock()
    # The bulk read returns the states; a single-calendar filter is the failed-attempt stamp.
    css.objects.filter.side_effect = lambda **kw: (
        states if "google_calendar_id__in" in kw else stamp
    )
    css.stamp = stamp
    inbound = mocker.patch("gcal_sync.reconcile.InboundSync").return_value
    inbound.process_calendar.return_value = (
        {"holds_created": 1, "holds_removed": 0},
        ["E"],
    )
    mocker.patch.object(
        reconcile, "acquire_provider_lock", side_effect=lambda cal: cal not in busy
    )
    release = mocker.patch.object(reconcile, "release_provider_lock")
    return inbound, release


def test_periodic_pull_picks_never_pulled_then_oldest_and_respects_the_batch(mocker):
    states = [
        _sync_state("recent", last=NOW - timedelta(hours=1)),
        _sync_state("old", last=NOW - timedelta(days=3)),
        _sync_state("older", last=NOW - timedelta(days=5)),
        _sync_state("never"),
    ]
    inbound, release = _fleet(mocker, states)
    totals, effects = reconcile.periodic_full_pull(SECRETS, batch_size=2)
    pulled = [c.args[0] for c in inbound.process_calendar.call_args_list]
    assert pulled == ["never", "older"]
    assert all(
        c.kwargs == {"full_pull": True} for c in inbound.process_calendar.call_args_list
    )
    assert totals["pulled"] == 2 and totals["holds_created"] == 2
    assert effects == ["E", "E"]
    assert release.call_count == 2


def test_periodic_pull_leaves_first_and_recovery_pulls_to_the_reconcile(mocker):
    states = [
        _sync_state("no-token", token=""),
        _sync_state("flagged", needs=True),
    ]
    inbound, _ = _fleet(mocker, states)
    totals, effects = reconcile.periodic_full_pull(SECRETS)
    inbound.process_calendar.assert_not_called()
    assert totals["pulled"] == 0 and effects == []


def test_periodic_pull_skips_a_locked_provider_and_counts_failures(mocker):
    from gcal_sync.google.client import GoogleApiError

    states = [_sync_state("busy"), _sync_state("broken")]
    inbound, release = _fleet(mocker, states, busy={"busy"})
    inbound.process_calendar.side_effect = GoogleApiError(500, "boom")
    totals, effects = reconcile.periodic_full_pull(SECRETS)
    assert totals["skipped"] == 1 and totals["failed"] == 1
    assert effects == []
    # Only the lock it took is released, even when the pull raises.
    release.assert_called_once_with("broken")
    # The failed attempt is stamped so it rotates to the back instead of blocking the batch.
    css = reconcile.CalendarSyncState
    assert css.objects.filter.call_args.kwargs == {"google_calendar_id": "broken"}
    assert "last_full_pull_at" in css.stamp.update.call_args.kwargs


def test_periodic_pull_with_no_active_mappings_does_nothing(mocker):
    scm = mocker.patch("gcal_sync.reconcile.StaffCalendarMapping")
    scm.objects.filter.return_value.values_list.return_value = []
    inbound = mocker.patch("gcal_sync.reconcile.InboundSync")
    assert reconcile.periodic_full_pull(SECRETS) == (
        {
            "pulled": 0,
            "skipped": 0,
            "failed": 0,
            "holds_created": 0,
            "holds_removed": 0,
        },
        [],
    )
    inbound.assert_not_called()


def test_periodic_full_pull_cron_returns_the_effects(mocker):
    from gcal_sync.handlers.periodic_full_pull import PeriodicFullPullCron

    pull = mocker.patch(
        "gcal_sync.handlers.periodic_full_pull.periodic_full_pull",
        return_value=({}, ["E"]),
    )
    cron = PeriodicFullPullCron.__new__(PeriodicFullPullCron)
    cron.secrets = SECRETS
    assert cron.execute() == ["E"]
    pull.assert_called_once_with(SECRETS)
