"""Tests for the reconcile flows: inbound recovery, outbound truth re-push, per-provider, and all."""

from types import SimpleNamespace

from gcal_sync.reconcile import (
    inbound_recovery,
    outbound_truth,
    reconcile_all,
    reconcile_provider,
    sweep_outbound,
)


def _mock_outbound_queries(mocker, appts):
    """Wire the module-level ORM mocks outbound_truth/sweep_outbound rely on. Returns the mocks."""
    ext = mocker.patch("gcal_sync.reconcile.AppointmentExternalIdentifier")
    ext.objects.filter.return_value.values_list.return_value = []
    appt = mocker.patch("gcal_sync.reconcile.Appointment")
    appt.objects.filter.return_value.values.return_value = appts
    aem = mocker.patch("gcal_sync.reconcile.AppointmentEventMapping")
    aem.objects.filter.return_value = []
    mocker.patch("gcal_sync.reconcile.snapshot_from_values", return_value="SNAP")
    return ext, appt, aem


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
    aem = mocker.patch("gcal_sync.reconcile.AppointmentEventMapping")
    aem.objects.filter.return_value = []  # no existing mappings prefetched
    mocker.patch("gcal_sync.reconcile.snapshot_from_values", return_value="SNAP")
    pushed = outbound_truth({}, [SimpleNamespace(canvas_staff_id="14", google_calendar_id="c1")])
    assert pushed == 1
    # Mappings are prefetched once for the pushable appointment ids only (terminal id 2 excluded)...
    aem.objects.filter.assert_called_once_with(canvas_appointment_id__in=["1"])
    # ...and the prefetched cache is handed to push so it does no per-appointment query.
    sync.push.assert_called_once_with("c1", "SNAP", {})


def test_outbound_truth_hands_existing_mapping_to_push_so_it_patches_not_inserts(mocker):
    # Duplicate-safety: an appointment that ALREADY has a mapping must be found in the prefetched
    # cache and handed to push, so push PATCHES the existing Google event instead of inserting a
    # second one. This is precisely the case a duplicate would come from if the cache were incomplete.
    sync = mocker.patch("gcal_sync.reconcile.SyncService").return_value
    ext = mocker.patch("gcal_sync.reconcile.AppointmentExternalIdentifier")
    ext.objects.filter.return_value.values_list.return_value = []
    appt = mocker.patch("gcal_sync.reconcile.Appointment")
    appt.objects.filter.return_value.values.return_value = [{"id": 7, "status": "confirmed"}]
    existing = SimpleNamespace(canvas_appointment_id="7", google_event_id="g-7")
    aem = mocker.patch("gcal_sync.reconcile.AppointmentEventMapping")
    aem.objects.filter.return_value = [existing]  # a mapping already exists for appt 7
    mocker.patch("gcal_sync.reconcile.snapshot_from_values", return_value="SNAP")

    outbound_truth({}, [SimpleNamespace(canvas_staff_id="14", google_calendar_id="c1")])

    # The cache is keyed by the appointment's string id and carries the existing mapping through to
    # push, which then resolves it (hit, not miss) and patches -> no duplicate insert.
    sync.push.assert_called_once_with("c1", "SNAP", {"7": existing})


def test_outbound_truth_skips_google_origin(mocker):
    sync = mocker.patch("gcal_sync.reconcile.SyncService").return_value
    ext = mocker.patch("gcal_sync.reconcile.AppointmentExternalIdentifier")
    ext.objects.filter.return_value.values_list.return_value = [1]  # appt 1 is google-origin
    appt = mocker.patch("gcal_sync.reconcile.Appointment")
    appt.objects.filter.return_value.values.return_value = [{"id": 1, "status": "confirmed"}]
    aem = mocker.patch("gcal_sync.reconcile.AppointmentEventMapping")
    aem.objects.filter.return_value = []
    mocker.patch("gcal_sync.reconcile.snapshot_from_values", return_value="SNAP")
    assert outbound_truth({}, [SimpleNamespace(canvas_staff_id="14", google_calendar_id="c1")]) == 0
    sync.push.assert_not_called()
    # Nothing pushable -> the prefetch queries for an empty id set (no wasted work either).
    aem.objects.filter.assert_called_once_with(canvas_appointment_id__in=[])


def test_outbound_truth_caps_total_pushes(mocker):
    # Bounded: a run performs at most max_pushes Google writes, then stops (resumes next run).
    sync = mocker.patch("gcal_sync.reconcile.SyncService").return_value
    _mock_outbound_queries(
        mocker,
        [{"id": 1, "status": "confirmed"}, {"id": 2, "status": "confirmed"}, {"id": 3, "status": "confirmed"}],
    )
    pushed = outbound_truth(
        {}, [SimpleNamespace(canvas_staff_id="14", google_calendar_id="c1")], max_pushes=2
    )
    assert pushed == 2
    assert sync.push.call_count == 2


def test_outbound_truth_marks_provider_synced_when_completed(mocker):
    mocker.patch("gcal_sync.reconcile.SyncService")
    _mock_outbound_queries(mocker, [{"id": 1, "status": "confirmed"}])
    mapping = SimpleNamespace(
        canvas_staff_id="14", google_calendar_id="c1", last_outbound_synced_at=None, save=mocker.Mock()
    )
    outbound_truth({}, [mapping])
    assert mapping.last_outbound_synced_at is not None  # stamped once its window completed
    mapping.save.assert_called_once()


def test_sweep_outbound_limits_calendars_and_passes_live_ids(mocker):
    sync = mocker.patch("gcal_sync.reconcile.SyncService").return_value
    sync.sweep_calendar.return_value = 3
    _mock_outbound_queries(mocker, [{"id": 5, "status": "confirmed"}])
    m1 = SimpleNamespace(canvas_staff_id="1", google_calendar_id="c1", last_outbound_synced_at=None)
    m2 = SimpleNamespace(canvas_staff_id="2", google_calendar_id="c2", last_outbound_synced_at=None)

    total = sweep_outbound({}, [m1, m2], max_calendars=1)

    assert total == 3
    assert sync.sweep_calendar.call_count == 1  # only ONE calendar swept this run
    # live_appointment_ids passed as a set of string appt ids
    assert sync.sweep_calendar.call_args.args[1] == {"5"}


def test_reconcile_provider_combines_inbound_outbound_blocks(mocker):
    inbound = mocker.patch("gcal_sync.reconcile.InboundSync").return_value
    inbound.process_calendar.return_value = ({}, ["HOLD"])
    mocker.patch("gcal_sync.reconcile.outbound_truth", return_value=3)
    mocker.patch("gcal_sync.reconcile.sweep_outbound", return_value=4)
    mocker.patch(
        "gcal_sync.reconcile.sync_all_blocks", return_value={"pushed": 2, "deleted": 1}
    )
    stats, effects = reconcile_provider(
        {}, SimpleNamespace(canvas_staff_id="14", google_calendar_id="c1")
    )
    assert effects == ["HOLD"]
    assert stats == {"pushed": 3, "swept": 4, "blocks_pushed": 2, "blocks_deleted": 1}


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
    mocker.patch("gcal_sync.reconcile.sweep_outbound", return_value=2)
    mocker.patch(
        "gcal_sync.reconcile.sync_all_blocks", return_value={"pushed": 1, "deleted": 0}
    )
    stats, effects = reconcile_all({})
    assert stats["mappings"] == 1
    assert stats["pushed"] == 5
    assert stats["swept"] == 2
    assert effects == ["E"]
