"""Tests for reconcile.py: provider locking, bounded outbound, sweep, reimport drain,
outbound backfill drain, purge chunks, fleet reimport queue, and helper functions.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from gcal_sync.channels import ChannelConfigError
from gcal_sync.google.auth import GoogleAuthError
from gcal_sync.google.client import GoogleApiError, GoogleRateLimitError
from gcal_sync.reconcile import (
    _full_pull_priority,
    _needs_full_pull,
    _outbound_priority,
    _outbound_window,
    _pushable_appointments,
    _rfc3339,
    acquire_provider_lock,
    cancel_fleet_reimport,
    drain_outbound_backfill,
    drain_reimport_queue,
    enqueue_fleet_reimport,
    outbound_truth,
    purge_holds_chunk,
    reimport_queue_depth,
    release_provider_lock,
    sweep_outbound,
)


# --- provider locking -----------------------------------------------------------------------------


def test_acquire_lock_succeeds_on_fresh_insert(mocker):
    psl = mocker.patch("gcal_sync.reconcile.ProviderSyncLock")
    psl.objects.filter.return_value.delete.return_value = None
    psl.objects.create.return_value = SimpleNamespace()
    assert acquire_provider_lock("cal@x") is True
    psl.objects.create.assert_called_once_with(google_calendar_id="cal@x")


def test_acquire_lock_returns_false_on_integrity_error(mocker):
    from django.db import IntegrityError

    psl = mocker.patch("gcal_sync.reconcile.ProviderSyncLock")
    psl.objects.filter.return_value.delete.return_value = None
    psl.objects.create.side_effect = IntegrityError("dup")
    assert acquire_provider_lock("cal@x") is False


def test_acquire_lock_reclaims_stale_lock(mocker):
    from django.db import IntegrityError

    psl = mocker.patch("gcal_sync.reconcile.ProviderSyncLock")
    # delete returns something (stale lock cleaned up)
    psl.objects.filter.return_value.delete.return_value = 1
    psl.objects.create.return_value = SimpleNamespace()
    assert acquire_provider_lock("cal@x") is True


def test_release_lock_deletes_row(mocker):
    psl = mocker.patch("gcal_sync.reconcile.ProviderSyncLock")
    release_provider_lock("cal@x")
    psl.objects.filter.assert_called_once_with(google_calendar_id="cal@x")
    psl.objects.filter.return_value.delete.assert_called_once()


# --- helper functions -----------------------------------------------------------------------------


def test_outbound_window_returns_arrow_range():
    start, end = _outbound_window()
    # start is ~1 month ago, end is ~1 year from now
    assert start < end


def test_rfc3339_format():
    import arrow
    when = arrow.get("2026-06-10T15:30:00Z")
    assert _rfc3339(when) == "2026-06-10T15:30:00Z"


def test_needs_full_pull_true_when_no_state():
    assert _needs_full_pull(None) is True


def test_needs_full_pull_true_when_no_token():
    assert _needs_full_pull(SimpleNamespace(sync_token="", needs_full_resync=False)) is True


def test_needs_full_pull_true_when_flagged():
    assert _needs_full_pull(SimpleNamespace(sync_token="tok", needs_full_resync=True)) is True


def test_needs_full_pull_false_when_healthy():
    assert _needs_full_pull(SimpleNamespace(sync_token="tok", needs_full_resync=False)) is False


def test_full_pull_priority_none_state():
    assert _full_pull_priority(None) == (0, "")


def test_full_pull_priority_with_state():
    from datetime import datetime, timezone

    state = SimpleNamespace(updated_at=datetime(2026, 6, 10, tzinfo=timezone.utc))
    p = _full_pull_priority(state)
    assert p[0] == 1
    assert "2026" in p[1]


def test_full_pull_priority_with_no_updated_at():
    state = SimpleNamespace(updated_at=None)
    assert _full_pull_priority(state) == (1, "")


def test_outbound_priority_none_timestamp():
    m = SimpleNamespace()
    assert _outbound_priority(m) == (0, 0.0)


def test_outbound_priority_with_timestamp():
    from datetime import datetime, timezone

    m = SimpleNamespace(last_outbound_synced_at=datetime(2026, 6, 10, tzinfo=timezone.utc))
    p = _outbound_priority(m)
    assert p[0] == 1
    assert p[1] > 0


# --- pushable_appointments -----------------------------------------------------------------------


def test_pushable_skips_terminal_and_google_origin(mocker):
    appt = mocker.patch("gcal_sync.reconcile.Appointment")
    appt.objects.filter.return_value.values.return_value = [
        {"id": 1, "status": "confirmed"},
        {"id": 2, "status": "cancelled"},
        {"id": 3, "status": "noshowed"},
        {"id": 4, "status": "confirmed"},
    ]
    m = SimpleNamespace(canvas_staff_id="14")
    result = _pushable_appointments(m, None, None, {4})
    # id=1 passes, id=2 cancelled, id=3 noshowed, id=4 google-origin
    assert len(result) == 1
    assert result[0]["id"] == 1


# --- outbound_truth bounded pushes ---------------------------------------------------------------


def test_outbound_truth_respects_max_pushes(mocker):
    sync = mocker.patch("gcal_sync.reconcile.SyncService").return_value
    ext = mocker.patch("gcal_sync.reconcile.AppointmentExternalIdentifier")
    ext.objects.filter.return_value.values_list.return_value = []
    aem = mocker.patch("gcal_sync.reconcile.AppointmentEventMapping")
    aem.objects.filter.return_value = []
    appt = mocker.patch("gcal_sync.reconcile.Appointment")
    appt.objects.filter.return_value.values.return_value = [
        {"id": 1, "status": "confirmed"},
        {"id": 2, "status": "confirmed"},
        {"id": 3, "status": "confirmed"},
    ]
    mocker.patch("gcal_sync.reconcile.snapshot_from_values", return_value="SNAP")
    pushed = outbound_truth(
        {},
        [SimpleNamespace(canvas_staff_id="14", google_calendar_id="c1")],
        max_pushes=2,
    )
    assert pushed == 2
    assert sync.push.call_count == 2


def test_outbound_truth_skip_mapped_drops_already_mapped(mocker):
    sync = mocker.patch("gcal_sync.reconcile.SyncService").return_value
    ext = mocker.patch("gcal_sync.reconcile.AppointmentExternalIdentifier")
    ext.objects.filter.return_value.values_list.return_value = []
    aem = mocker.patch("gcal_sync.reconcile.AppointmentEventMapping")
    # appt "1" already has a mapping
    existing_mapping = SimpleNamespace(canvas_appointment_id="1", google_event_id="g-1")
    aem.objects.filter.return_value = [existing_mapping]
    appt = mocker.patch("gcal_sync.reconcile.Appointment")
    appt.objects.filter.return_value.values.return_value = [
        {"id": 1, "status": "confirmed"},
        {"id": 2, "status": "confirmed"},
    ]
    mocker.patch("gcal_sync.reconcile.snapshot_from_values", return_value="SNAP")
    pushed = outbound_truth(
        {},
        [SimpleNamespace(canvas_staff_id="14", google_calendar_id="c1")],
        skip_mapped=True,
    )
    # Only appt 2 is pushed (appt 1 is already mapped and skip_mapped=True)
    assert pushed == 1
    sync.push.assert_called_once()


def test_outbound_truth_handles_rate_limit(mocker):
    sync = mocker.patch("gcal_sync.reconcile.SyncService").return_value
    sync.push.side_effect = GoogleRateLimitError(429, "rate limit")
    ext = mocker.patch("gcal_sync.reconcile.AppointmentExternalIdentifier")
    ext.objects.filter.return_value.values_list.return_value = []
    aem = mocker.patch("gcal_sync.reconcile.AppointmentEventMapping")
    aem.objects.filter.return_value = []
    appt = mocker.patch("gcal_sync.reconcile.Appointment")
    appt.objects.filter.return_value.values.return_value = [
        {"id": 1, "status": "confirmed"},
        {"id": 2, "status": "confirmed"},
    ]
    mocker.patch("gcal_sync.reconcile.snapshot_from_values", return_value="SNAP")
    mapping = SimpleNamespace(
        canvas_staff_id="14",
        google_calendar_id="c1",
        last_outbound_synced_at=None,
    )
    pushed = outbound_truth({}, [mapping])
    # Rate-limited -> stops and does NOT stamp last_outbound_synced_at
    assert pushed == 0


def test_outbound_truth_handles_api_error(mocker):
    sync = mocker.patch("gcal_sync.reconcile.SyncService").return_value
    sync.push.side_effect = GoogleApiError(500, "server error")
    ext = mocker.patch("gcal_sync.reconcile.AppointmentExternalIdentifier")
    ext.objects.filter.return_value.values_list.return_value = []
    aem = mocker.patch("gcal_sync.reconcile.AppointmentEventMapping")
    aem.objects.filter.return_value = []
    appt = mocker.patch("gcal_sync.reconcile.Appointment")
    appt.objects.filter.return_value.values.return_value = [
        {"id": 1, "status": "confirmed"},
    ]
    mocker.patch("gcal_sync.reconcile.snapshot_from_values", return_value="SNAP")
    mapping = SimpleNamespace(
        canvas_staff_id="14",
        google_calendar_id="c1",
        last_outbound_synced_at=None,
    )
    # Errors are logged, not raised; run completes
    pushed = outbound_truth({}, [mapping])
    assert pushed == 0


def test_outbound_truth_stamps_synced_at_when_completed(mocker):
    sync = mocker.patch("gcal_sync.reconcile.SyncService").return_value
    ext = mocker.patch("gcal_sync.reconcile.AppointmentExternalIdentifier")
    ext.objects.filter.return_value.values_list.return_value = []
    aem = mocker.patch("gcal_sync.reconcile.AppointmentEventMapping")
    aem.objects.filter.return_value = []
    appt = mocker.patch("gcal_sync.reconcile.Appointment")
    appt.objects.filter.return_value.values.return_value = [
        {"id": 1, "status": "confirmed"},
    ]
    mocker.patch("gcal_sync.reconcile.snapshot_from_values", return_value="SNAP")
    mapping = SimpleNamespace(
        canvas_staff_id="14",
        google_calendar_id="c1",
        last_outbound_synced_at=None,
        save=mocker.Mock(),
    )
    outbound_truth({}, [mapping])
    assert mapping.last_outbound_synced_at is not None
    mapping.save.assert_called_once()


def test_outbound_truth_save_failure_doesnt_abort(mocker):
    sync = mocker.patch("gcal_sync.reconcile.SyncService").return_value
    ext = mocker.patch("gcal_sync.reconcile.AppointmentExternalIdentifier")
    ext.objects.filter.return_value.values_list.return_value = []
    aem = mocker.patch("gcal_sync.reconcile.AppointmentEventMapping")
    aem.objects.filter.return_value = []
    appt = mocker.patch("gcal_sync.reconcile.Appointment")
    appt.objects.filter.return_value.values.return_value = [
        {"id": 1, "status": "confirmed"},
    ]
    mocker.patch("gcal_sync.reconcile.snapshot_from_values", return_value="SNAP")
    mapping = SimpleNamespace(
        canvas_staff_id="14",
        google_calendar_id="c1",
        last_outbound_synced_at=None,
        save=mocker.Mock(side_effect=Exception("db boom")),
    )
    # Should not raise — the save failure is swallowed
    pushed = outbound_truth({}, [mapping])
    assert pushed == 1


# --- sweep_outbound -------------------------------------------------------------------------------


def test_sweep_outbound_delegates_to_sync_service(mocker):
    sync = mocker.patch("gcal_sync.reconcile.SyncService").return_value
    sync.sweep_calendar.return_value = 3
    ext = mocker.patch("gcal_sync.reconcile.AppointmentExternalIdentifier")
    ext.objects.filter.return_value.values_list.return_value = []
    appt = mocker.patch("gcal_sync.reconcile.Appointment")
    appt.objects.filter.return_value.values.return_value = []
    mapping = SimpleNamespace(
        canvas_staff_id="14",
        google_calendar_id="c1",
        last_outbound_synced_at=None,
    )
    deleted = sweep_outbound({}, [mapping])
    assert deleted == 3
    sync.sweep_calendar.assert_called_once()


def test_sweep_outbound_caps_calendars(mocker):
    sync = mocker.patch("gcal_sync.reconcile.SyncService").return_value
    sync.sweep_calendar.return_value = 0
    ext = mocker.patch("gcal_sync.reconcile.AppointmentExternalIdentifier")
    ext.objects.filter.return_value.values_list.return_value = []
    appt = mocker.patch("gcal_sync.reconcile.Appointment")
    appt.objects.filter.return_value.values.return_value = []
    mappings = [
        SimpleNamespace(canvas_staff_id=str(i), google_calendar_id=f"c{i}")
        for i in range(5)
    ]
    sweep_outbound({}, mappings, max_calendars=2)
    assert sync.sweep_calendar.call_count == 2


def test_sweep_outbound_handles_error(mocker):
    sync = mocker.patch("gcal_sync.reconcile.SyncService").return_value
    sync.sweep_calendar.side_effect = GoogleApiError(500, "boom")
    ext = mocker.patch("gcal_sync.reconcile.AppointmentExternalIdentifier")
    ext.objects.filter.return_value.values_list.return_value = []
    appt = mocker.patch("gcal_sync.reconcile.Appointment")
    appt.objects.filter.return_value.values.return_value = []
    mapping = SimpleNamespace(
        canvas_staff_id="14",
        google_calendar_id="c1",
        last_outbound_synced_at=None,
    )
    deleted = sweep_outbound({}, [mapping])
    assert deleted == 0


# --- inbound_recovery error handling --------------------------------------------------------------


def test_inbound_recovery_catches_errors_per_calendar(mocker):
    inbound = mocker.patch("gcal_sync.reconcile.InboundSync").return_value
    inbound.process_calendar.side_effect = GoogleApiError(500, "boom")
    mocker.patch("gcal_sync.reconcile.CalendarSyncState").objects.filter.return_value = []
    effects = __import__("gcal_sync.reconcile", fromlist=["inbound_recovery"]).inbound_recovery(
        {}, [SimpleNamespace(google_calendar_id="c1")]
    )
    assert effects == []


# --- purge_holds_chunk ----------------------------------------------------------------------------


def test_purge_holds_chunk_partial(mocker):
    aei = mocker.patch("gcal_sync.reconcile.AppointmentExternalIdentifier")
    qs = aei.objects.filter.return_value.exclude.return_value
    qs.filter.return_value.order_by.return_value.values_list.return_value.distinct.return_value.__getitem__ = (
        lambda self, key: [101, 102, 103]
    )
    se = mocker.patch("gcal_sync.reconcile.ScheduleEvent")
    iem = mocker.patch("gcal_sync.reconcile.InboundEventMapping")
    phc = mocker.patch("gcal_sync.reconcile.PendingHoldCreate")
    mapping = SimpleNamespace(canvas_staff_id="14", google_calendar_id="cal@x")
    effects, last_id, done = purge_holds_chunk(mapping, limit=5, after_id="100")
    assert len(effects) == 3
    assert done is True  # 3 < 5 = done
    # When done, mappings and pending markers are cleared
    iem.objects.filter.assert_called_once_with(google_calendar_id="cal@x")
    phc.objects.filter.assert_called_once_with(google_calendar_id="cal@x")


def test_purge_holds_chunk_not_done_when_full(mocker):
    aei = mocker.patch("gcal_sync.reconcile.AppointmentExternalIdentifier")
    qs = aei.objects.filter.return_value.exclude.return_value
    # When after_id is empty, the code goes straight to .order_by() (no .filter())
    qs.order_by.return_value.values_list.return_value.distinct.return_value.__getitem__ = (
        lambda self, key: [101, 102]
    )
    se = mocker.patch("gcal_sync.reconcile.ScheduleEvent")
    iem = mocker.patch("gcal_sync.reconcile.InboundEventMapping")
    phc = mocker.patch("gcal_sync.reconcile.PendingHoldCreate")
    mapping = SimpleNamespace(canvas_staff_id="14", google_calendar_id="cal@x")
    effects, last_id, done = purge_holds_chunk(mapping, limit=2, after_id="")
    assert len(effects) == 2
    assert done is False  # 2 == 2 -> not done
    # Mappings NOT cleared when not done
    iem.objects.filter.assert_not_called()
    phc.objects.filter.assert_not_called()


def test_purge_holds_chunk_empty_result(mocker):
    aei = mocker.patch("gcal_sync.reconcile.AppointmentExternalIdentifier")
    qs = aei.objects.filter.return_value.exclude.return_value
    qs.order_by.return_value.values_list.return_value.distinct.return_value.__getitem__ = (
        lambda self, key: []
    )
    se = mocker.patch("gcal_sync.reconcile.ScheduleEvent")
    iem = mocker.patch("gcal_sync.reconcile.InboundEventMapping")
    phc = mocker.patch("gcal_sync.reconcile.PendingHoldCreate")
    mapping = SimpleNamespace(canvas_staff_id="14", google_calendar_id="cal@x")
    effects, last_id, done = purge_holds_chunk(mapping, limit=10, after_id="prev")
    assert effects == []
    assert done is True
    assert last_id == "prev"


# --- fleet reimport queue -------------------------------------------------------------------------


def test_enqueue_fleet_reimport_creates_rows(mocker):
    scm = mocker.patch("gcal_sync.reconcile.StaffCalendarMapping")
    scm.objects.filter.return_value.order_by.return_value = [
        SimpleNamespace(google_calendar_id="c1"),
        SimpleNamespace(google_calendar_id="c2"),
    ]
    rq = mocker.patch("gcal_sync.reconcile.ReimportQueue")
    rq.objects.get_or_create.side_effect = [
        (SimpleNamespace(), True),
        (SimpleNamespace(), False),  # already exists
    ]
    queued = enqueue_fleet_reimport()
    assert queued == 1  # one newly created


def test_enqueue_fleet_reimport_with_limit(mocker):
    scm = mocker.patch("gcal_sync.reconcile.StaffCalendarMapping")
    scm.objects.filter.return_value.order_by.return_value.__getitem__ = lambda self, key: [
        SimpleNamespace(google_calendar_id="c1"),
    ]
    rq = mocker.patch("gcal_sync.reconcile.ReimportQueue")
    rq.objects.get_or_create.return_value = (SimpleNamespace(), True)
    queued = enqueue_fleet_reimport(limit=1)
    assert queued == 1


def test_reimport_queue_depth(mocker):
    rq = mocker.patch("gcal_sync.reconcile.ReimportQueue")
    rq.objects.count.return_value = 7
    assert reimport_queue_depth() == 7


def test_cancel_fleet_reimport_empties_queue(mocker):
    rq = mocker.patch("gcal_sync.reconcile.ReimportQueue")
    rq.objects.count.return_value = 3
    rq.objects.all.return_value.delete.return_value = None
    cleared = cancel_fleet_reimport()
    assert cleared == 3
    rq.objects.all.return_value.delete.assert_called_once()


# --- drain_reimport_queue -------------------------------------------------------------------------


def test_drain_reimport_queue_processes_entries(mocker):
    rq = mocker.patch("gcal_sync.reconcile.ReimportQueue")
    entry = SimpleNamespace(
        google_calendar_id="c1", attempts=0, save=mocker.Mock(), delete=mocker.Mock()
    )
    rq.objects.order_by.return_value.__getitem__ = lambda self, key: [entry]
    rq.objects.count.return_value = 0
    scm = mocker.patch("gcal_sync.reconcile.StaffCalendarMapping")
    mapping = SimpleNamespace(canvas_staff_id="14", google_calendar_id="c1", active=True)
    scm.objects.filter.return_value.first.return_value = mapping
    mocker.patch("gcal_sync.reconcile.acquire_provider_lock", return_value=True)
    mocker.patch("gcal_sync.reconcile.release_provider_lock")
    mocker.patch(
        "gcal_sync.reconcile.reimport_provider",
        return_value=({"holds_created": 5, "holds_updated": 0, "holds_unchanged": 0, "holds_removed": 0}, ["E"]),
    )
    totals, effects = drain_reimport_queue({}, batch_size=4)
    assert totals["processed"] == 1
    assert totals["holds_created"] == 5
    assert effects == ["E"]
    entry.delete.assert_called_once()


def test_drain_reimport_queue_drops_deactivated_mapping(mocker):
    rq = mocker.patch("gcal_sync.reconcile.ReimportQueue")
    entry = SimpleNamespace(
        google_calendar_id="c1", attempts=0, save=mocker.Mock(), delete=mocker.Mock()
    )
    rq.objects.order_by.return_value.__getitem__ = lambda self, key: [entry]
    rq.objects.count.return_value = 0
    scm = mocker.patch("gcal_sync.reconcile.StaffCalendarMapping")
    scm.objects.filter.return_value.first.return_value = None  # mapping gone
    totals, effects = drain_reimport_queue({}, batch_size=4)
    assert totals["dropped"] == 1
    entry.delete.assert_called_once()


def test_drain_reimport_queue_skips_locked_provider(mocker):
    rq = mocker.patch("gcal_sync.reconcile.ReimportQueue")
    entry = SimpleNamespace(
        google_calendar_id="c1", attempts=0, save=mocker.Mock(), delete=mocker.Mock()
    )
    rq.objects.order_by.return_value.__getitem__ = lambda self, key: [entry]
    rq.objects.count.return_value = 1
    scm = mocker.patch("gcal_sync.reconcile.StaffCalendarMapping")
    scm.objects.filter.return_value.first.return_value = SimpleNamespace(
        canvas_staff_id="14", google_calendar_id="c1", active=True
    )
    mocker.patch("gcal_sync.reconcile.acquire_provider_lock", return_value=False)
    totals, effects = drain_reimport_queue({}, batch_size=4)
    assert totals["skipped"] == 1
    entry.delete.assert_not_called()


def test_drain_reimport_queue_retries_on_error(mocker):
    rq = mocker.patch("gcal_sync.reconcile.ReimportQueue")
    entry = SimpleNamespace(
        google_calendar_id="c1", attempts=0, save=mocker.Mock(), delete=mocker.Mock()
    )
    rq.objects.order_by.return_value.__getitem__ = lambda self, key: [entry]
    rq.objects.count.return_value = 1
    scm = mocker.patch("gcal_sync.reconcile.StaffCalendarMapping")
    scm.objects.filter.return_value.first.return_value = SimpleNamespace(
        canvas_staff_id="14", google_calendar_id="c1", active=True
    )
    mocker.patch("gcal_sync.reconcile.acquire_provider_lock", return_value=True)
    mocker.patch("gcal_sync.reconcile.release_provider_lock")
    mocker.patch(
        "gcal_sync.reconcile.reimport_provider",
        side_effect=GoogleApiError(500, "boom"),
    )
    totals, effects = drain_reimport_queue({}, batch_size=4)
    assert totals["failed"] == 1
    assert entry.attempts == 1
    entry.save.assert_called_once()  # saved for retry
    entry.delete.assert_not_called()


def test_drain_reimport_queue_drops_after_max_attempts(mocker):
    rq = mocker.patch("gcal_sync.reconcile.ReimportQueue")
    entry = SimpleNamespace(
        google_calendar_id="c1", attempts=2, save=mocker.Mock(), delete=mocker.Mock()
    )
    rq.objects.order_by.return_value.__getitem__ = lambda self, key: [entry]
    rq.objects.count.return_value = 0
    scm = mocker.patch("gcal_sync.reconcile.StaffCalendarMapping")
    scm.objects.filter.return_value.first.return_value = SimpleNamespace(
        canvas_staff_id="14", google_calendar_id="c1", active=True
    )
    mocker.patch("gcal_sync.reconcile.acquire_provider_lock", return_value=True)
    mocker.patch("gcal_sync.reconcile.release_provider_lock")
    mocker.patch(
        "gcal_sync.reconcile.reimport_provider",
        side_effect=GoogleAuthError("auth fail"),
    )
    totals, effects = drain_reimport_queue({}, batch_size=4)
    assert totals["dropped"] == 1
    entry.delete.assert_called_once()


def test_drain_reimport_queue_noop_when_empty(mocker):
    rq = mocker.patch("gcal_sync.reconcile.ReimportQueue")
    rq.objects.order_by.return_value.__getitem__ = lambda self, key: []
    rq.objects.count.return_value = 0
    totals, effects = drain_reimport_queue({}, batch_size=4)
    assert totals["processed"] == 0
    assert effects == []


# --- drain_outbound_backfill ----------------------------------------------------------------------


def _mock_scm_for_drain(mocker, mappings):
    """Mock StaffCalendarMapping so the first filter(active=True) returns mappings and
    subsequent filter() calls return a countable mock (for the `remaining` count).
    """
    scm = mocker.patch("gcal_sync.reconcile.StaffCalendarMapping")
    remaining_qs = MagicMock()
    remaining_qs.count.return_value = 0
    scm.objects.filter.side_effect = [mappings, remaining_qs]
    return scm


def test_drain_outbound_backfill_processes_providers(mocker):
    mapping = SimpleNamespace(
        canvas_staff_id="14",
        google_calendar_id="c1",
        active=True,
        last_outbound_synced_at=None,
    )
    _mock_scm_for_drain(mocker, [mapping])
    mocker.patch("gcal_sync.reconcile.acquire_provider_lock", return_value=True)
    mocker.patch("gcal_sync.reconcile.release_provider_lock")
    mocker.patch("gcal_sync.reconcile.outbound_truth", return_value=10)
    totals = drain_outbound_backfill({}, providers_per_tick=1, pushes_per_provider=40)
    assert totals["providers"] == 1
    assert totals["pushed"] == 10


def test_drain_outbound_backfill_skips_locked(mocker):
    mapping = SimpleNamespace(
        canvas_staff_id="14",
        google_calendar_id="c1",
        active=True,
        last_outbound_synced_at=None,
    )
    _mock_scm_for_drain(mocker, [mapping])
    mocker.patch("gcal_sync.reconcile.acquire_provider_lock", return_value=False)
    totals = drain_outbound_backfill({}, providers_per_tick=1, pushes_per_provider=40)
    assert totals["skipped"] == 1
    assert totals["pushed"] == 0


def test_drain_outbound_backfill_reports_remaining(mocker):
    mapping = SimpleNamespace(
        canvas_staff_id="14",
        google_calendar_id="c1",
        active=True,
        last_outbound_synced_at=None,
    )
    scm = mocker.patch("gcal_sync.reconcile.StaffCalendarMapping")
    remaining_qs = MagicMock()
    remaining_qs.count.return_value = 5
    scm.objects.filter.side_effect = [[mapping], remaining_qs]
    mocker.patch("gcal_sync.reconcile.acquire_provider_lock", return_value=True)
    mocker.patch("gcal_sync.reconcile.release_provider_lock")
    mocker.patch("gcal_sync.reconcile.outbound_truth", return_value=0)
    totals = drain_outbound_backfill({}, providers_per_tick=1, pushes_per_provider=40)
    assert totals["providers"] == 1


# --- reconcile_provider error handling ------------------------------------------------------------


def test_reconcile_provider_handles_inbound_error(mocker):
    inbound = mocker.patch("gcal_sync.reconcile.InboundSync").return_value
    inbound.process_calendar.side_effect = GoogleApiError(500, "fail")
    mocker.patch("gcal_sync.reconcile.outbound_truth", return_value=0)
    mocker.patch("gcal_sync.reconcile.sweep_outbound", return_value=0)
    mocker.patch(
        "gcal_sync.reconcile.sync_all_blocks", return_value={"pushed": 0, "deleted": 0}
    )
    from gcal_sync.reconcile import reconcile_provider

    stats, effects = reconcile_provider(
        {}, SimpleNamespace(canvas_staff_id="14", google_calendar_id="c1")
    )
    # Inbound error is caught; outbound/blocks still run
    assert stats["pushed"] == 0
    assert effects == []
