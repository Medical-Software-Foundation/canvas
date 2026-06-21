"""Tests for the re-import reset path: a clean re-import must wipe a provider's imported state
(cancel existing holds + drop inbound mappings) before the full pull, so events that were cancelled
out-of-band come back and no live duplicates are created.

Models/effects are mocked — no DB or network.
"""

from types import SimpleNamespace

from gcal_sync.reconcile import reimport_provider, reset_inbound_for_provider


def _mapping():
    return SimpleNamespace(canvas_staff_id="14", google_calendar_id="joe@x")


def test_reset_cancels_existing_holds_and_clears_mappings(mocker):
    aei = mocker.patch("gcal_sync.reconcile.AppointmentExternalIdentifier")
    aei.objects.filter.return_value.exclude.return_value.values_list.return_value.distinct.return_value = [
        101,
        102,
    ]
    iem = mocker.patch("gcal_sync.reconcile.InboundEventMapping")
    schedule_event = mocker.patch("gcal_sync.reconcile.ScheduleEvent")

    effects = reset_inbound_for_provider(_mapping())

    # One cancel effect per existing hold.
    assert len(effects) == 2
    assert schedule_event.call_count == 2
    # Inbound mappings for THIS calendar are dropped so the pull recreates fresh.
    iem.objects.filter.assert_called_once_with(google_calendar_id="joe@x")
    iem.objects.filter.return_value.delete.assert_called_once()


def test_reimport_resets_then_full_pulls(mocker):
    mocker.patch("gcal_sync.reconcile.reset_inbound_for_provider", return_value=["CANCEL"])
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
    # Reset (cancel) effects are applied before the freshly-imported holds.
    assert effects == ["CANCEL", "HOLD"]
    assert stats["holds_created"] == 5
