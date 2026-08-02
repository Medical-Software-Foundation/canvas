"""Tests for inbound.py: dry-run mode, force_rebuild, convergence guard, import window guard,
provider-scoped lookups, event_line, dry_trace, and process_calendar dry_run mode.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import arrow
import pytest

from gcal_sync.google.client import GoogleApiError
from gcal_sync.google.event_builder import CANVAS_APPT_ID_KEY, build_event_body, content_hash
from gcal_sync.inbound import InboundSync, _dry_trace, _event_line, _event_log, _MAX_TRACE

SECRETS = {"GOOGLE_SERVICE_ACCOUNT_JSON": '{"client_email": "svc@x.iam", "private_key": "KEY"}'}


def _inbound(mocker):
    inbound = InboundSync(SECRETS, client_factory=lambda cal: object())
    mocker.patch.object(inbound._sync, "push")
    mocker.patch.object(inbound._sync, "remove")
    return inbound


def _stats(dry_run=False):
    s = {
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
    if dry_run:
        s["trace"] = []
    return s


# --- _event_line ---------------------------------------------------------------------------------


def test_event_line_masks_private_title():
    event = {
        "start": {"dateTime": "2026-06-10T15:00:00Z"},
        "end": {"dateTime": "2026-06-10T15:30:00Z"},
        "visibility": "private",
        "summary": "Secret stuff",
    }
    line = _event_line(event)
    assert "Secret" not in line
    assert "Busy" in line


def test_event_line_shows_public_title():
    event = {
        "start": {"dateTime": "2026-06-10T15:00:00Z"},
        "end": {"dateTime": "2026-06-10T15:30:00Z"},
        "summary": "Team standup",
    }
    line = _event_line(event)
    assert "Team standup" in line


def test_event_line_no_start():
    line = _event_line({"summary": "No time"})
    assert "(no start)" in line


def test_event_line_no_summary():
    event = {
        "start": {"dateTime": "2026-06-10T15:00:00Z"},
        "end": {"dateTime": "2026-06-10T15:30:00Z"},
    }
    line = _event_line(event)
    assert "Busy" in line


# --- _dry_trace ----------------------------------------------------------------------------------


def test_dry_trace_appends_when_trace_present():
    stats = {"trace": []}
    event = {"start": {"dateTime": "2026-06-10T15:00:00Z"}, "summary": "Test"}
    _dry_trace(stats, "would import", event)
    assert len(stats["trace"]) == 1
    assert "would import" in stats["trace"][0]


def test_dry_trace_noop_without_trace_key():
    stats = {}
    _dry_trace(stats, "would import", {"summary": "Test"})
    assert "trace" not in stats


def test_dry_trace_caps_at_max():
    stats = {"trace": ["x"] * _MAX_TRACE}
    _dry_trace(stats, "overflow", {"summary": "Test"})
    assert len(stats["trace"]) == _MAX_TRACE + 1
    assert "capped" in stats["trace"][-1]
    # One more after cap -> no growth
    _dry_trace(stats, "overflow again", {"summary": "Test"})
    assert len(stats["trace"]) == _MAX_TRACE + 1


# --- _event_log -----------------------------------------------------------------------------------


def test_event_log_emits_when_verbose(mocker):
    log = mocker.patch("gcal_sync.inbound.log")
    _event_log(True, "create", "cal", "p1", "g1")
    log.info.assert_called_once()


def test_event_log_silent_when_not_verbose(mocker):
    log = mocker.patch("gcal_sync.inbound.log")
    _event_log(False, "create", "cal", "p1", "g1")
    log.info.assert_not_called()


# --- _within_import_window ------------------------------------------------------------------------


def test_within_import_window_true_for_current_events(mocker):
    inbound = _inbound(mocker)
    event = {
        "start": {"dateTime": arrow.utcnow().format("YYYY-MM-DD[T]HH:mm:ss[Z]")},
    }
    assert inbound._within_import_window(event) is True


def test_within_import_window_false_for_far_future(mocker):
    inbound = _inbound(mocker)
    event = {
        "start": {"dateTime": arrow.utcnow().shift(years=2).format("YYYY-MM-DD[T]HH:mm:ss[Z]")},
    }
    assert inbound._within_import_window(event) is False


def test_within_import_window_false_for_far_past(mocker):
    inbound = _inbound(mocker)
    event = {
        "start": {"dateTime": arrow.utcnow().shift(years=-2).format("YYYY-MM-DD[T]HH:mm:ss[Z]")},
    }
    assert inbound._within_import_window(event) is False


def test_within_import_window_true_when_no_start(mocker):
    inbound = _inbound(mocker)
    assert inbound._within_import_window({}) is True


# --- _canvas_id_for_google_event ------------------------------------------------------------------


def test_canvas_id_for_google_event_returns_id(mocker):
    aei = mocker.patch("gcal_sync.inbound.AppointmentExternalIdentifier")
    aei.objects.filter.return_value.exclude.return_value.values_list.return_value.first.return_value = 42
    result = InboundSync._canvas_id_for_google_event("g1", "p1")
    assert result == "42"


def test_canvas_id_for_google_event_returns_none(mocker):
    aei = mocker.patch("gcal_sync.inbound.AppointmentExternalIdentifier")
    aei.objects.filter.return_value.exclude.return_value.values_list.return_value.first.return_value = None
    result = InboundSync._canvas_id_for_google_event("g1", "p1")
    assert result is None


# --- _external_hold_exists ------------------------------------------------------------------------


def test_external_hold_exists_true(mocker):
    aei = mocker.patch("gcal_sync.inbound.AppointmentExternalIdentifier")
    aei.objects.filter.return_value.exists.return_value = True
    assert InboundSync._external_hold_exists("g1", "p1") is True


def test_external_hold_exists_false(mocker):
    aei = mocker.patch("gcal_sync.inbound.AppointmentExternalIdentifier")
    aei.objects.filter.return_value.exists.return_value = False
    assert InboundSync._external_hold_exists("g1", "p1") is False


# --- _hold_delete_effect --------------------------------------------------------------------------


def test_hold_delete_effect_returns_none_when_no_canvas_id(mocker):
    inbound = _inbound(mocker)
    mocker.patch.object(inbound, "_canvas_id_for_google_event", return_value=None)
    assert inbound._hold_delete_effect("g1", "p1") is None


def test_hold_delete_effect_returns_effect_when_found(mocker):
    inbound = _inbound(mocker)
    mocker.patch.object(inbound, "_canvas_id_for_google_event", return_value="appt-1")
    se = mocker.patch("gcal_sync.inbound.ScheduleEvent")
    result = inbound._hold_delete_effect("g1", "p1")
    se.assert_called_once_with(instance_id="appt-1")
    assert result is not None


# --- _hold_update_effect --------------------------------------------------------------------------


def test_hold_update_effect_returns_none_when_no_canvas_id(mocker):
    inbound = _inbound(mocker)
    mocker.patch.object(inbound, "_canvas_id_for_google_event", return_value=None)
    assert inbound._hold_update_effect("g1", {}, "p1") is None


def test_hold_update_effect_returns_none_when_no_window(mocker):
    inbound = _inbound(mocker)
    mocker.patch.object(inbound, "_canvas_id_for_google_event", return_value="appt-1")
    mocker.patch("gcal_sync.inbound.parse_event_window", return_value=None)
    assert inbound._hold_update_effect("g1", {}, "p1") is None


# --- process_calendar dry_run mode ----------------------------------------------------------------


def test_process_calendar_dry_run_does_not_save_token(mocker):
    state = SimpleNamespace(sync_token="", needs_full_resync=True, save=mocker.Mock())
    css = mocker.patch("gcal_sync.inbound.CalendarSyncState")
    css.objects.get_or_create.return_value = (state, False)
    client = SimpleNamespace(
        list_event_deltas=lambda *a, **kw: ([], "newtok"),
    )
    inbound = InboundSync(SECRETS, client_factory=lambda c: client)
    stats, effects = inbound.process_calendar("c1", dry_run=True)
    assert "trace" in stats  # dry run populates trace
    # Token and state NOT saved in dry_run mode
    state.save.assert_not_called()


def test_process_calendar_dry_run_410_does_not_save(mocker):
    state = SimpleNamespace(sync_token="tok", needs_full_resync=False, save=mocker.Mock())
    css = mocker.patch("gcal_sync.inbound.CalendarSyncState")
    css.objects.get_or_create.return_value = (state, False)
    client = SimpleNamespace(
        list_event_deltas=lambda *a, **kw: (_ for _ in ()).throw(GoogleApiError(410, "gone")),
    )
    inbound = InboundSync(SECRETS, client_factory=lambda c: client)
    stats, effects = inbound.process_calendar("c1", dry_run=True)
    assert stats["full_resync"] is True
    state.save.assert_not_called()


# --- unmarked event: convergence guard blocks recreate unless force_rebuild --------------------


def test_convergence_guard_blocks_recreate(mocker):
    iem = mocker.patch("gcal_sync.inbound.InboundEventMapping")
    iem.objects.filter.return_value.first.return_value = None
    phc = mocker.patch("gcal_sync.inbound.PendingHoldCreate")
    phc.objects.filter.return_value.first.return_value = None
    mocker.patch("gcal_sync.inbound.schedule_event_note_type_id", return_value="nt-1")
    mocker.patch("gcal_sync.inbound.provider_and_location", return_value=("14", "loc-1"))
    inbound = _inbound(mocker)
    mocker.patch.object(inbound, "_canvas_id_for_google_event", return_value=None)
    mocker.patch.object(inbound, "_external_hold_exists", return_value=True)
    stats = _stats()
    effects = inbound._apply("cal", {"id": "g1", "status": "confirmed"}, stats)
    assert effects == []
    assert stats["ignored"] == 1


def test_force_rebuild_bypasses_convergence_guard(mocker):
    iem = mocker.patch("gcal_sync.inbound.InboundEventMapping")
    iem.objects.filter.return_value.first.return_value = None
    phc = mocker.patch("gcal_sync.inbound.PendingHoldCreate")
    phc.objects.filter.return_value.first.return_value = None
    mocker.patch("gcal_sync.inbound.schedule_event_note_type_id", return_value="nt-1")
    mocker.patch("gcal_sync.inbound.provider_and_location", return_value=("14", "loc-1"))
    mocker.patch("gcal_sync.inbound.build_hold_effect", return_value="HOLD")
    inbound = _inbound(mocker)
    mocker.patch.object(inbound, "_canvas_id_for_google_event", return_value=None)
    mocker.patch.object(inbound, "_external_hold_exists", return_value=True)
    stats = _stats()
    effects = inbound._apply("cal", {"id": "g1", "status": "confirmed"}, stats, force_rebuild=True)
    assert effects == ["HOLD"]
    assert stats["holds_created"] == 1


# --- unmarked event: all-day and private filter ---------------------------------------------------


def test_all_day_event_skipped_when_not_ingesting(mocker):
    iem = mocker.patch("gcal_sync.inbound.InboundEventMapping")
    iem.objects.filter.return_value.first.return_value = None
    phc = mocker.patch("gcal_sync.inbound.PendingHoldCreate")
    phc.objects.filter.return_value.first.return_value = None
    mocker.patch("gcal_sync.inbound.schedule_event_note_type_id", return_value="nt-1")
    mocker.patch("gcal_sync.inbound.provider_and_location", return_value=("14", "loc-1"))
    inbound = _inbound(mocker)
    inbound._ingest_all_day = False
    mocker.patch.object(inbound, "_canvas_id_for_google_event", return_value=None)
    mocker.patch.object(inbound, "_external_hold_exists", return_value=False)
    stats = _stats()
    event = {"id": "g1", "status": "confirmed", "start": {"date": "2026-06-10"}}
    effects = inbound._apply("cal", event, stats)
    assert effects == []
    assert stats["ignored"] == 1


def test_private_event_skipped_when_not_ingesting(mocker):
    iem = mocker.patch("gcal_sync.inbound.InboundEventMapping")
    iem.objects.filter.return_value.first.return_value = None
    phc = mocker.patch("gcal_sync.inbound.PendingHoldCreate")
    phc.objects.filter.return_value.first.return_value = None
    mocker.patch("gcal_sync.inbound.schedule_event_note_type_id", return_value="nt-1")
    mocker.patch("gcal_sync.inbound.provider_and_location", return_value=("14", "loc-1"))
    inbound = _inbound(mocker)
    inbound._ingest_private = False
    mocker.patch.object(inbound, "_canvas_id_for_google_event", return_value=None)
    mocker.patch.object(inbound, "_external_hold_exists", return_value=False)
    stats = _stats()
    event = {"id": "g1", "status": "confirmed", "visibility": "private"}
    effects = inbound._apply("cal", event, stats)
    assert effects == []
    assert stats["ignored"] == 1


# --- unmarked event: cancelled deletes pending marker + mapping in non-dry mode -------------------


def test_cancelled_event_clears_pending_marker(mocker):
    existing = SimpleNamespace(google_event_id="g-1", delete=mocker.Mock())
    mocker.patch(
        "gcal_sync.inbound.InboundEventMapping"
    ).objects.filter.return_value.first.return_value = existing
    pending = SimpleNamespace(delete=mocker.Mock())
    mocker.patch(
        "gcal_sync.inbound.PendingHoldCreate"
    ).objects.filter.return_value.first.return_value = pending
    mocker.patch("gcal_sync.inbound.schedule_event_note_type_id", return_value="nt-1")
    mocker.patch("gcal_sync.inbound.provider_and_location", return_value=("14", "loc-1"))
    inbound = _inbound(mocker)
    mocker.patch.object(inbound, "_hold_delete_effect", return_value="DEL")
    stats = _stats()
    effects = inbound._apply("cal", {"id": "g-1", "status": "cancelled"}, stats)
    assert effects == ["DEL"]
    existing.delete.assert_called_once()
    pending.delete.assert_called_once()


def test_cancelled_event_no_effect_when_no_hold(mocker):
    mocker.patch(
        "gcal_sync.inbound.InboundEventMapping"
    ).objects.filter.return_value.first.return_value = None
    mocker.patch(
        "gcal_sync.inbound.PendingHoldCreate"
    ).objects.filter.return_value.first.return_value = None
    mocker.patch("gcal_sync.inbound.schedule_event_note_type_id", return_value="nt-1")
    mocker.patch("gcal_sync.inbound.provider_and_location", return_value=("14", "loc-1"))
    inbound = _inbound(mocker)
    mocker.patch.object(inbound, "_hold_delete_effect", return_value=None)
    stats = _stats()
    effects = inbound._apply("cal", {"id": "g-1", "status": "cancelled"}, stats)
    assert effects == []
    assert stats["ignored"] == 1


# --- unmarked event: outside import window is skipped ---


def test_event_outside_window_is_skipped(mocker):
    iem = mocker.patch("gcal_sync.inbound.InboundEventMapping")
    iem.objects.filter.return_value.first.return_value = None
    phc = mocker.patch("gcal_sync.inbound.PendingHoldCreate")
    phc.objects.filter.return_value.first.return_value = None
    mocker.patch("gcal_sync.inbound.schedule_event_note_type_id", return_value="nt-1")
    mocker.patch("gcal_sync.inbound.provider_and_location", return_value=("14", "loc-1"))
    inbound = _inbound(mocker)
    stats = _stats()
    event = {
        "id": "g1",
        "status": "confirmed",
        "start": {"dateTime": arrow.utcnow().shift(years=2).format("YYYY-MM-DD[T]HH:mm:ss[Z]")},
    }
    effects = inbound._apply("cal", event, stats)
    assert effects == []
    assert stats["ignored"] == 1


# --- unmarked event: no-op guard (unchanged hash) ------------------------------------------------


def test_unchanged_hash_skips_update(mocker):
    from gcal_sync.google.event_builder import google_event_content_hash

    # Use a date within the import window (relative to now)
    now_str = arrow.utcnow().shift(days=1).format("YYYY-MM-DD[T]HH:mm:ss[Z]")
    end_str = arrow.utcnow().shift(days=1, minutes=30).format("YYYY-MM-DD[T]HH:mm:ss[Z]")
    event = {
        "id": "g1",
        "status": "confirmed",
        "summary": "Meeting",
        "start": {"dateTime": now_str},
        "end": {"dateTime": end_str},
    }
    event_hash = google_event_content_hash(event)
    existing = SimpleNamespace(google_event_id="g1", last_applied_hash=event_hash)
    iem = mocker.patch("gcal_sync.inbound.InboundEventMapping")
    iem.objects.filter.return_value.first.return_value = existing
    phc = mocker.patch("gcal_sync.inbound.PendingHoldCreate")
    phc.objects.filter.return_value.first.return_value = None
    mocker.patch("gcal_sync.inbound.schedule_event_note_type_id", return_value="nt-1")
    mocker.patch("gcal_sync.inbound.provider_and_location", return_value=("14", "loc-1"))
    inbound = _inbound(mocker)
    mocker.patch.object(inbound, "_canvas_id_for_google_event", return_value="appt-1")
    stats = _stats()
    effects = inbound._apply("cal", event, stats)
    assert effects == []
    assert stats["holds_unchanged"] == 1


# --- marked event: no mapping found => ignored ---


def test_marked_event_no_mapping_is_ignored(mocker):
    mocker.patch(
        "gcal_sync.inbound.AppointmentEventMapping"
    ).objects.filter.return_value.first.return_value = None
    inbound = _inbound(mocker)
    event = build_event_body({
        "appointment_id": "appt-1",
        "visit_type": "Visit",
        "start_time": datetime(2026, 6, 10, 15, 0, tzinfo=timezone.utc),
        "duration_minutes": 30,
        "location": "Clinic",
        "meeting_link": None,
        "status": "confirmed",
    })
    event["id"] = "g1"
    stats = _stats()
    effects = inbound._apply("cal", event, stats)
    assert effects == []
    assert stats["ignored"] == 1


# --- marked event: dry_run reverts without actually pushing ---


def test_marked_event_dry_run_does_not_push(mocker):
    body = build_event_body({
        "appointment_id": "appt-1",
        "visit_type": "Visit",
        "start_time": datetime(2026, 6, 10, 15, 0, tzinfo=timezone.utc),
        "duration_minutes": 30,
        "location": "Clinic",
        "meeting_link": None,
        "status": "confirmed",
    })
    event = dict(body)
    event["id"] = "g-1"
    event["summary"] = "Changed by provider"
    mapping = SimpleNamespace(last_pushed_hash=content_hash(body))
    mocker.patch(
        "gcal_sync.inbound.AppointmentEventMapping"
    ).objects.filter.return_value.first.return_value = mapping
    inbound = _inbound(mocker)
    stats = _stats(dry_run=True)
    effects = inbound._apply("cal", event, stats, dry_run=True)
    assert effects == []
    assert stats["reverted"] == 1
    inbound._sync.push.assert_not_called()


# --- marked event: reverts to None => removes event ---


def test_marked_revert_removes_when_snapshot_none(mocker):
    body = build_event_body({
        "appointment_id": "appt-1",
        "visit_type": "Visit",
        "start_time": datetime(2026, 6, 10, 15, 0, tzinfo=timezone.utc),
        "duration_minutes": 30,
        "location": "Clinic",
        "meeting_link": None,
        "status": "confirmed",
    })
    event = dict(body)
    event["id"] = "g-1"
    event["summary"] = "Changed"
    mapping = SimpleNamespace(last_pushed_hash=content_hash(body))
    mocker.patch(
        "gcal_sync.inbound.AppointmentEventMapping"
    ).objects.filter.return_value.first.return_value = mapping
    mocker.patch("gcal_sync.inbound.build_snapshot", return_value=None)
    inbound = _inbound(mocker)
    stats = _stats()
    inbound._apply("cal", event, stats)
    assert stats["reverted"] == 1
    inbound._sync.remove.assert_called_once_with("appt-1")


# --- update writes mapping on non-dry run ---


def test_update_writes_mapping_on_non_dry(mocker):
    existing = SimpleNamespace(google_event_id="g1", last_applied_hash="")
    iem = mocker.patch("gcal_sync.inbound.InboundEventMapping")
    iem.objects.filter.return_value.first.return_value = existing
    phc = mocker.patch("gcal_sync.inbound.PendingHoldCreate")
    phc.objects.filter.return_value.first.return_value = None
    mocker.patch("gcal_sync.inbound.schedule_event_note_type_id", return_value="nt-1")
    mocker.patch("gcal_sync.inbound.provider_and_location", return_value=("14", "loc-1"))
    inbound = _inbound(mocker)
    mocker.patch.object(inbound, "_canvas_id_for_google_event", return_value="appt-1")
    mocker.patch.object(inbound, "_hold_update_effect", return_value="UPD")
    stats = _stats()
    event = {"id": "g1", "status": "confirmed", "summary": "New title"}
    effects = inbound._apply("cal", event, stats)
    assert effects == ["UPD"]
    iem.objects.update_or_create.assert_called_once()


def test_update_skips_mapping_write_on_dry_run(mocker):
    existing = SimpleNamespace(google_event_id="g1", last_applied_hash="")
    iem = mocker.patch("gcal_sync.inbound.InboundEventMapping")
    iem.objects.filter.return_value.first.return_value = existing
    phc = mocker.patch("gcal_sync.inbound.PendingHoldCreate")
    phc.objects.filter.return_value.first.return_value = None
    mocker.patch("gcal_sync.inbound.schedule_event_note_type_id", return_value="nt-1")
    mocker.patch("gcal_sync.inbound.provider_and_location", return_value=("14", "loc-1"))
    inbound = _inbound(mocker)
    mocker.patch.object(inbound, "_canvas_id_for_google_event", return_value="appt-1")
    mocker.patch.object(inbound, "_hold_update_effect", return_value="UPD")
    stats = _stats(dry_run=True)
    event = {"id": "g1", "status": "confirmed", "summary": "New title"}
    effects = inbound._apply("cal", event, stats, dry_run=True)
    assert effects == ["UPD"]
    iem.objects.update_or_create.assert_not_called()


# --- update returns None -> ignored ---


def test_update_returns_none_is_ignored(mocker):
    existing = SimpleNamespace(google_event_id="g1", last_applied_hash="")
    iem = mocker.patch("gcal_sync.inbound.InboundEventMapping")
    iem.objects.filter.return_value.first.return_value = existing
    phc = mocker.patch("gcal_sync.inbound.PendingHoldCreate")
    phc.objects.filter.return_value.first.return_value = None
    mocker.patch("gcal_sync.inbound.schedule_event_note_type_id", return_value="nt-1")
    mocker.patch("gcal_sync.inbound.provider_and_location", return_value=("14", "loc-1"))
    inbound = _inbound(mocker)
    mocker.patch.object(inbound, "_canvas_id_for_google_event", return_value="appt-1")
    mocker.patch.object(inbound, "_hold_update_effect", return_value=None)
    stats = _stats()
    event = {"id": "g1", "status": "confirmed", "summary": "New"}
    effects = inbound._apply("cal", event, stats)
    assert effects == []
    assert stats["ignored"] == 1
