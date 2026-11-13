"""Tests for the re-import reset path: a clean re-import must wipe a provider's imported state
(cancel existing holds + drop inbound mappings) before the full pull, so events that were cancelled
out-of-band come back and no live duplicates are created.

Models/effects are mocked — no DB or network.
"""

from types import SimpleNamespace

from gcal_sync.reconcile import purge_holds_chunk, reimport_provider, reset_inbound_for_provider


def _mapping():
    return SimpleNamespace(canvas_staff_id="14", google_calendar_id="joe@x")


def test_reset_cancels_existing_holds_and_clears_mappings(mocker):
    aei = mocker.patch("gcal_sync.reconcile.AppointmentExternalIdentifier")
    aei.objects.filter.return_value.exclude.return_value.values_list.return_value.distinct.return_value = [
        101,
        102,
    ]
    iem = mocker.patch("gcal_sync.reconcile.InboundEventMapping")
    phc = mocker.patch("gcal_sync.reconcile.PendingHoldCreate")
    rdh = mocker.patch("gcal_sync.reconcile.RemovedDayHold")
    schedule_event = mocker.patch("gcal_sync.reconcile.ScheduleEvent")

    effects = reset_inbound_for_provider(_mapping())

    # One cancel effect per existing hold.
    assert len(effects) == 2
    assert schedule_event.call_count == 2
    # Inbound mappings for THIS calendar are dropped so the pull recreates fresh.
    iem.objects.filter.assert_called_once_with(google_calendar_id="joe@x")
    iem.objects.filter.return_value.delete.assert_called_once()
    # PendingHoldCreate markers for THIS calendar are also cleared.
    phc.objects.filter.assert_called_once_with(google_calendar_id="joe@x")
    phc.objects.filter.return_value.delete.assert_called_once()
    # Every hold is cancelled on purpose, so no day keeps its "removed by the sync" record.
    rdh.objects.filter.assert_called_once_with(google_calendar_id="joe@x")
    rdh.objects.filter.return_value.delete.assert_called_once()


def test_final_purge_chunk_drops_removed_day_records(mocker):
    # A purged provider's days stay cancelled until a deliberate re-import: without this, a delta
    # could hold a day again just because the sync had once removed it.
    aei = mocker.patch("gcal_sync.reconcile.AppointmentExternalIdentifier")
    aei.objects.filter.return_value.exclude.return_value.order_by.return_value.values_list.return_value.distinct.return_value = [
        101
    ]
    mocker.patch("gcal_sync.reconcile.InboundEventMapping")
    mocker.patch("gcal_sync.reconcile.PendingHoldCreate")
    rdh = mocker.patch("gcal_sync.reconcile.RemovedDayHold")
    mocker.patch("gcal_sync.reconcile.ScheduleEvent")

    _effects, _last, done = purge_holds_chunk(_mapping(), limit=50)

    assert done is True
    rdh.objects.filter.assert_called_once_with(google_calendar_id="joe@x")
    rdh.objects.filter.return_value.delete.assert_called_once()


def test_purge_chunk_keeps_removed_day_records_until_the_last_chunk(mocker):
    aei = mocker.patch("gcal_sync.reconcile.AppointmentExternalIdentifier")
    aei.objects.filter.return_value.exclude.return_value.order_by.return_value.values_list.return_value.distinct.return_value = [
        101,
        102,
    ]
    mocker.patch("gcal_sync.reconcile.ScheduleEvent")
    rdh = mocker.patch("gcal_sync.reconcile.RemovedDayHold")

    _effects, _last, done = purge_holds_chunk(_mapping(), limit=2)

    assert done is False
    rdh.objects.filter.assert_not_called()


def test_reimport_resets_then_full_pulls(mocker):
    state = SimpleNamespace(sync_token="stale-token", needs_full_resync=False, save=mocker.Mock())
    css = mocker.patch("gcal_sync.reconcile.CalendarSyncState")
    css.objects.get_or_create.return_value = (state, False)
    inbound = mocker.patch("gcal_sync.reconcile.InboundSync")
    inbound.return_value.process_calendar.return_value = ({"holds_created": 5}, ["HOLD"])

    stats, effects = reimport_provider({}, _mapping())

    # Cursor cleared and full resync forced so events.list returns ALL events.
    assert state.sync_token == ""
    assert state.needs_full_resync is True
    state.save.assert_called_once()
    # Re-import now does a force_rebuild pull (no separate reset step).
    assert effects == ["HOLD"]
    assert stats["holds_created"] == 5
