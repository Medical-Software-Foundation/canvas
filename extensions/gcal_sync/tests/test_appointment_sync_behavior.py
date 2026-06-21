"""Behavioral tests for AppointmentSyncHandler.compute routing and _handle_upsert branches."""

from types import SimpleNamespace

from canvas_sdk.events import EventType
from gcal_sync.handlers.appointment_sync import AppointmentSyncHandler


def _handler(event_type, secrets=None):
    h = AppointmentSyncHandler.__new__(AppointmentSyncHandler)
    h.event = SimpleNamespace(type=event_type, target=SimpleNamespace(id="appt-1"))
    h.secrets = secrets or {}
    return h


def test_cancel_event_routes_to_delete(mocker):
    svc = mocker.patch("gcal_sync.handlers.appointment_sync.SyncService").return_value
    assert _handler(EventType.APPOINTMENT_CANCELED).compute() == []
    svc.remove.assert_called_once_with("appt-1")


def test_upsert_skips_google_origin_records(mocker):
    mocker.patch(
        "gcal_sync.handlers.appointment_sync.google_origin_event_id", return_value="g-1"
    )
    svc = mocker.patch("gcal_sync.handlers.appointment_sync.SyncService").return_value
    bs = mocker.patch("gcal_sync.handlers.appointment_sync.build_snapshot")
    _handler(EventType.APPOINTMENT_CREATED).compute()
    bs.assert_not_called()
    svc.push.assert_not_called()


def test_upsert_removes_when_snapshot_none(mocker):
    mocker.patch("gcal_sync.handlers.appointment_sync.google_origin_event_id", return_value=None)
    mocker.patch("gcal_sync.handlers.appointment_sync.build_snapshot", return_value=None)
    svc = mocker.patch("gcal_sync.handlers.appointment_sync.SyncService").return_value
    _handler(EventType.APPOINTMENT_UPDATED).compute()
    svc.remove.assert_called_once_with("appt-1")


def test_upsert_skips_schedule_events(mocker):
    mocker.patch("gcal_sync.handlers.appointment_sync.google_origin_event_id", return_value=None)
    mocker.patch(
        "gcal_sync.handlers.appointment_sync.build_snapshot",
        return_value=({"appointment_id": "appt-1"}, "14", True),  # is_schedule_event=True
    )
    svc = mocker.patch("gcal_sync.handlers.appointment_sync.SyncService").return_value
    _handler(EventType.APPOINTMENT_CREATED).compute()
    svc.push.assert_not_called()


def test_upsert_skips_unenrolled_provider(mocker):
    mocker.patch("gcal_sync.handlers.appointment_sync.google_origin_event_id", return_value=None)
    mocker.patch(
        "gcal_sync.handlers.appointment_sync.build_snapshot",
        return_value=({"appointment_id": "appt-1"}, "14", False),
    )
    scm = mocker.patch("gcal_sync.handlers.appointment_sync.StaffCalendarMapping")
    scm.objects.filter.return_value.first.return_value = None
    svc = mocker.patch("gcal_sync.handlers.appointment_sync.SyncService").return_value
    _handler(EventType.APPOINTMENT_CREATED).compute()
    svc.push.assert_not_called()


def test_upsert_pushes_for_enrolled_provider(mocker):
    mocker.patch("gcal_sync.handlers.appointment_sync.google_origin_event_id", return_value=None)
    snap = {"appointment_id": "appt-1"}
    mocker.patch(
        "gcal_sync.handlers.appointment_sync.build_snapshot", return_value=(snap, "14", False)
    )
    scm = mocker.patch("gcal_sync.handlers.appointment_sync.StaffCalendarMapping")
    scm.objects.filter.return_value.first.return_value = SimpleNamespace(
        google_calendar_id="j@r.com"
    )
    svc = mocker.patch("gcal_sync.handlers.appointment_sync.SyncService").return_value
    _handler(EventType.APPOINTMENT_CREATED).compute()
    svc.push.assert_called_once_with("j@r.com", snap)


def test_safe_swallows_google_errors_only(mocker):
    from gcal_sync.google.client import GoogleApiError

    mocker.patch("gcal_sync.handlers.appointment_sync.google_origin_event_id", return_value=None)
    mocker.patch(
        "gcal_sync.handlers.appointment_sync.build_snapshot", side_effect=GoogleApiError(500, "x")
    )
    # Expected Google error is logged, not raised.
    assert _handler(EventType.APPOINTMENT_CREATED).compute() == []
