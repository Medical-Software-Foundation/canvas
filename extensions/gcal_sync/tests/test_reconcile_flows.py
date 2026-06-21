"""Tests for the reconcile flows: inbound recovery, outbound truth re-push, per-provider, and all."""

from types import SimpleNamespace

from gcal_sync.reconcile import (
    inbound_recovery,
    outbound_truth,
    reconcile_all,
    reconcile_provider,
)


def test_inbound_recovery_pulls_each_calendar(mocker):
    inbound = mocker.patch("gcal_sync.reconcile.InboundSync").return_value
    inbound.process_calendar.return_value = ({}, ["E1"])
    # No stored sync state -> c1 is a (first-time) full pull, under the cap.
    mocker.patch("gcal_sync.reconcile.CalendarSyncState").objects.filter.return_value = []
    effects = inbound_recovery({}, [SimpleNamespace(google_calendar_id="c1")])
    assert effects == ["E1"]
    inbound.process_calendar.assert_called_once_with("c1")


def test_inbound_recovery_caps_full_pulls_but_runs_all_deltas(mocker):
    inbound = mocker.patch("gcal_sync.reconcile.InboundSync").return_value
    inbound.process_calendar.return_value = ({}, [])
    # Two calendars already have a live sync token (cheap deltas); three are first-time full pulls.
    synced = [
        SimpleNamespace(google_calendar_id="d1", sync_token="t", needs_full_resync=False, updated_at=None),
        SimpleNamespace(google_calendar_id="d2", sync_token="t", needs_full_resync=False, updated_at=None),
    ]
    mocker.patch("gcal_sync.reconcile.CalendarSyncState").objects.filter.return_value = synced
    mappings = [SimpleNamespace(google_calendar_id=c) for c in ("d1", "d2", "f1", "f2", "f3")]
    inbound_recovery({}, mappings, max_full_pulls=1)
    pulled = {call.args[0] for call in inbound.process_calendar.call_args_list}
    # Both deltas always run; only ONE of the three full pulls runs this pass.
    assert {"d1", "d2"}.issubset(pulled)
    assert len(pulled & {"f1", "f2", "f3"}) == 1
    assert inbound.process_calendar.call_count == 3


def test_outbound_truth_pushes_only_live_non_origin(mocker):
    sync = mocker.patch("gcal_sync.reconcile.SyncService").return_value
    ext = mocker.patch("gcal_sync.reconcile.AppointmentExternalIdentifier")
    ext.objects.filter.return_value.values_list.return_value = []  # no google-origin records
    appt = mocker.patch("gcal_sync.reconcile.Appointment")
    appt.objects.filter.return_value.values.return_value = [
        {"id": 1, "status": "confirmed"},
        {"id": 2, "status": "cancelled"},  # terminal -> skipped
    ]
    mocker.patch("gcal_sync.reconcile.snapshot_from_values", return_value="SNAP")
    pushed = outbound_truth({}, [SimpleNamespace(canvas_staff_id="14", google_calendar_id="c1")])
    assert pushed == 1
    sync.push.assert_called_once_with("c1", "SNAP")


def test_outbound_truth_skips_google_origin(mocker):
    sync = mocker.patch("gcal_sync.reconcile.SyncService").return_value
    ext = mocker.patch("gcal_sync.reconcile.AppointmentExternalIdentifier")
    ext.objects.filter.return_value.values_list.return_value = [1]  # appt 1 is google-origin
    appt = mocker.patch("gcal_sync.reconcile.Appointment")
    appt.objects.filter.return_value.values.return_value = [{"id": 1, "status": "confirmed"}]
    mocker.patch("gcal_sync.reconcile.snapshot_from_values", return_value="SNAP")
    assert outbound_truth({}, [SimpleNamespace(canvas_staff_id="14", google_calendar_id="c1")]) == 0
    sync.push.assert_not_called()


def test_reconcile_provider_combines_inbound_outbound_blocks(mocker):
    inbound = mocker.patch("gcal_sync.reconcile.InboundSync").return_value
    inbound.process_calendar.return_value = ({}, ["HOLD"])
    mocker.patch("gcal_sync.reconcile.outbound_truth", return_value=3)
    mocker.patch(
        "gcal_sync.reconcile.sync_all_blocks", return_value={"pushed": 2, "deleted": 1}
    )
    stats, effects = reconcile_provider(
        {}, SimpleNamespace(canvas_staff_id="14", google_calendar_id="c1")
    )
    assert effects == ["HOLD"]
    assert stats == {"pushed": 3, "blocks_pushed": 2, "blocks_deleted": 1}


def test_reconcile_all_noop_without_mappings(mocker):
    scm = mocker.patch("gcal_sync.reconcile.StaffCalendarMapping")
    scm.objects.filter.return_value = []
    stats, effects = reconcile_all({})
    assert stats["mappings"] == 0
    assert effects == []


def test_reconcile_all_runs_full_pass(mocker):
    scm = mocker.patch("gcal_sync.reconcile.StaffCalendarMapping")
    scm.objects.filter.return_value = [SimpleNamespace(google_calendar_id="c1")]
    mocker.patch("gcal_sync.reconcile.inbound_recovery", return_value=["E"])
    mocker.patch("gcal_sync.reconcile.outbound_truth", return_value=5)
    mocker.patch(
        "gcal_sync.reconcile.sync_all_blocks", return_value={"pushed": 1, "deleted": 0}
    )
    stats, effects = reconcile_all({})
    assert stats["mappings"] == 1
    assert stats["pushed"] == 5
    assert effects == ["E"]
