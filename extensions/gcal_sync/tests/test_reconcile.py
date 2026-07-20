"""Tests for reconcile helpers: the ``reset_inbound_for_provider`` wipe (used by Purge), the
non-destructive re-import, and the per-provider action lock.

Models/effects are mocked — no DB or network.
"""

from types import SimpleNamespace

from django.db import IntegrityError

from gcal_sync.reconcile import (
    acquire_provider_lock,
    cancel_fleet_reimport,
    drain_reimport_queue,
    enqueue_fleet_reimport,
    reimport_provider,
    release_provider_lock,
    reset_inbound_for_provider,
)


def _mapping():
    return SimpleNamespace(canvas_staff_id="14", google_calendar_id="joe@x")


def test_acquire_provider_lock_succeeds_when_free(mocker):
    lock = mocker.patch("gcal_sync.reconcile.ProviderSyncLock")
    lock.objects.create.return_value = object()
    assert acquire_provider_lock("c1") is True
    lock.objects.create.assert_called_once_with(google_calendar_id="c1")
    lock.objects.filter.assert_called_once()  # stale locks reclaimed before claiming


def test_acquire_provider_lock_returns_false_when_held(mocker):
    lock = mocker.patch("gcal_sync.reconcile.ProviderSyncLock")
    lock.objects.create.side_effect = IntegrityError(
        "duplicate key"
    )  # someone holds it
    assert acquire_provider_lock("c1") is False


def test_release_provider_lock_deletes_row(mocker):
    lock = mocker.patch("gcal_sync.reconcile.ProviderSyncLock")
    release_provider_lock("c1")
    lock.objects.filter.assert_called_once_with(google_calendar_id="c1")
    lock.objects.filter.return_value.delete.assert_called_once()


def test_reset_cancels_existing_holds_and_clears_mappings(mocker):
    aei = mocker.patch("gcal_sync.reconcile.AppointmentExternalIdentifier")
    aei.objects.filter.return_value.exclude.return_value.values_list.return_value.distinct.return_value = [
        101,
        102,
    ]
    iem = mocker.patch("gcal_sync.reconcile.InboundEventMapping")
    phc = mocker.patch("gcal_sync.reconcile.PendingHoldCreate")
    schedule_event = mocker.patch("gcal_sync.reconcile.ScheduleEvent")

    effects = reset_inbound_for_provider(_mapping())

    # One cancel effect per existing hold.
    assert len(effects) == 2
    assert schedule_event.call_count == 2
    # Inbound mappings AND pending-create markers for THIS calendar are dropped so the pull rebuilds
    # fresh (a stale pending marker would otherwise make the rebuild skip the event as "in flight").
    iem.objects.filter.assert_called_once_with(google_calendar_id="joe@x")
    phc.objects.filter.assert_called_once_with(google_calendar_id="joe@x")
    iem.objects.filter.return_value.delete.assert_called_once()


def _queue_entry(mocker, calendar_id, attempts=0):
    return SimpleNamespace(
        google_calendar_id=calendar_id,
        attempts=attempts,
        delete=mocker.Mock(),
        save=mocker.Mock(),
    )


def test_enqueue_fleet_reimport_is_idempotent(mocker):
    m1 = SimpleNamespace(google_calendar_id="a@x")
    m2 = SimpleNamespace(google_calendar_id="b@x")
    scm = mocker.patch("gcal_sync.reconcile.StaffCalendarMapping")
    scm.objects.filter.return_value.order_by.return_value = [m1, m2]
    rq = mocker.patch("gcal_sync.reconcile.ReimportQueue")
    # a@x is new, b@x already queued -> only the new one is counted.
    rq.objects.get_or_create.side_effect = [(object(), True), (object(), False)]
    assert enqueue_fleet_reimport() == 1
    assert rq.objects.get_or_create.call_count == 2


def test_drain_rebuilds_batch_and_deletes_finished(mocker):
    e1, e2 = _queue_entry(mocker, "a@x"), _queue_entry(mocker, "b@x")
    rq = mocker.patch("gcal_sync.reconcile.ReimportQueue")
    rq.objects.order_by.return_value = [e1, e2]
    rq.objects.count.return_value = 0
    scm = mocker.patch("gcal_sync.reconcile.StaffCalendarMapping")
    scm.objects.filter.return_value.first.side_effect = [_mapping(), _mapping()]
    mocker.patch("gcal_sync.reconcile.acquire_provider_lock", return_value=True)
    rel = mocker.patch("gcal_sync.reconcile.release_provider_lock")
    mocker.patch(
        "gcal_sync.reconcile.reimport_provider",
        return_value=({"holds_created": 3}, ["E"]),
    )
    totals, effects = drain_reimport_queue({}, batch_size=5)
    assert totals["processed"] == 2
    assert totals["holds_created"] == 6
    assert effects == [
        "E",
        "E",
    ]  # each rebuilt provider's effects returned for the cron to apply
    e1.delete.assert_called_once()  # finished -> removed from the queue
    e2.delete.assert_called_once()
    assert rel.call_count == 2  # lock always released


def test_drain_leaves_locked_provider_queued(mocker):
    e1 = _queue_entry(mocker, "a@x")
    rq = mocker.patch("gcal_sync.reconcile.ReimportQueue")
    rq.objects.order_by.return_value = [e1]
    rq.objects.count.return_value = 1
    scm = mocker.patch("gcal_sync.reconcile.StaffCalendarMapping")
    scm.objects.filter.return_value.first.return_value = _mapping()
    mocker.patch(
        "gcal_sync.reconcile.acquire_provider_lock", return_value=False
    )  # busy
    ri = mocker.patch("gcal_sync.reconcile.reimport_provider")
    totals, _ = drain_reimport_queue({})
    assert totals["skipped"] == 1
    ri.assert_not_called()  # not re-imported this tick
    e1.delete.assert_not_called()  # stays queued for the next tick


def test_drain_drops_provider_whose_mapping_vanished(mocker):
    e1 = _queue_entry(mocker, "gone@x")
    rq = mocker.patch("gcal_sync.reconcile.ReimportQueue")
    rq.objects.order_by.return_value = [e1]
    rq.objects.count.return_value = 0
    scm = mocker.patch("gcal_sync.reconcile.StaffCalendarMapping")
    scm.objects.filter.return_value.first.return_value = None  # deactivated/unmapped
    ri = mocker.patch("gcal_sync.reconcile.reimport_provider")
    totals, _ = drain_reimport_queue({})
    assert totals["dropped"] == 1
    ri.assert_not_called()
    e1.delete.assert_called_once()  # dropped from the queue


def test_drain_retries_then_drops_after_max_attempts(mocker):
    from gcal_sync.google.client import GoogleApiError

    # One attempt below the cap -> save (retry); at the cap -> delete (give up).
    e_retry = _queue_entry(mocker, "flaky@x", attempts=0)
    e_final = _queue_entry(mocker, "broken@x", attempts=2)
    rq = mocker.patch("gcal_sync.reconcile.ReimportQueue")
    rq.objects.order_by.return_value = [e_retry, e_final]
    rq.objects.count.return_value = 1
    scm = mocker.patch("gcal_sync.reconcile.StaffCalendarMapping")
    scm.objects.filter.return_value.first.side_effect = [_mapping(), _mapping()]
    mocker.patch("gcal_sync.reconcile.acquire_provider_lock", return_value=True)
    mocker.patch("gcal_sync.reconcile.release_provider_lock")
    mocker.patch(
        "gcal_sync.reconcile.reimport_provider",
        side_effect=GoogleApiError(500, "boom"),
    )
    totals, _ = drain_reimport_queue({})
    assert totals["failed"] == 2
    assert e_retry.attempts == 1
    e_retry.save.assert_called_once()  # under the cap -> retried next tick
    e_retry.delete.assert_not_called()
    assert e_final.attempts == 3
    e_final.delete.assert_called_once()  # hit the cap -> dropped
    assert totals["dropped"] == 1


def test_cancel_fleet_reimport_clears_queue(mocker):
    rq = mocker.patch("gcal_sync.reconcile.ReimportQueue")
    rq.objects.count.return_value = 7
    assert cancel_fleet_reimport() == 7  # reports how many were waiting
    rq.objects.all.return_value.delete.assert_called_once()  # queue emptied -> drain no-ops


def test_reimport_rebuilds_without_cancelling_first(mocker):
    # Non-destructive: re-import must NOT mass-cancel the provider's holds. It clears the cursor and
    # does a force_rebuild full pull that adopts/recreates from Google — no up-front cancellation
    # (mass-cancelling and relying on a window-bounded rebuild removed holds providers still had).
    reset = mocker.patch("gcal_sync.reconcile.reset_inbound_for_provider")
    state = SimpleNamespace(
        sync_token="stale-token", needs_full_resync=False, save=mocker.Mock()
    )
    css = mocker.patch("gcal_sync.reconcile.CalendarSyncState")
    css.objects.get_or_create.return_value = (state, False)
    inbound = mocker.patch("gcal_sync.reconcile.InboundSync")
    inbound.return_value.process_calendar.return_value = (
        {"holds_created": 5},
        ["HOLD"],
    )

    stats, effects = reimport_provider({}, _mapping())

    reset.assert_not_called()  # no mass-cancel — this is the destructive step we removed
    assert state.sync_token == ""  # cursor cleared -> events.list returns ALL events
    assert state.needs_full_resync is True
    state.save.assert_called_once()
    inbound.return_value.process_calendar.assert_called_once_with(
        _mapping().google_calendar_id, force_rebuild=True, dry_run=False, verbose=False
    )
    assert effects == ["HOLD"]  # only the rebuilt holds, nothing cancelled
    assert stats["holds_created"] == 5
