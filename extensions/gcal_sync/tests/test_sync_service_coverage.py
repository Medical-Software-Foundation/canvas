"""Tests for sync_service.py: adopt-don't-duplicate, sweep_calendar, mapping cache."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from gcal_sync.google.client import GoogleApiError
from gcal_sync.sync_service import SyncService

VALID_SA = '{"client_email": "svc@x.iam", "private_key": "KEY"}'


def _snapshot(appt_id="appt-1"):
    return {
        "appointment_id": appt_id,
        "visit_type": "Visit",
        "start_time": datetime(2026, 6, 10, 15, 0, tzinfo=timezone.utc),
        "duration_minutes": 30,
        "location": "Clinic",
        "meeting_link": None,
        "status": "confirmed",
    }


def _mock_model(mocker, existing=None):
    model = mocker.patch("gcal_sync.sync_service.AppointmentEventMapping")
    model.DoesNotExist = type("DoesNotExist", (Exception,), {})
    if existing is None:
        model.objects.get.side_effect = model.DoesNotExist
    else:
        model.objects.get.return_value = existing
    model.objects.create.side_effect = lambda **kw: SimpleNamespace(**kw)
    model.objects.update_or_create.side_effect = lambda **kw: (
        SimpleNamespace(**kw.get("defaults", {}), **{k: v for k, v in kw.items() if k != "defaults"}),
        True,
    )
    return model


class FakeClient:
    def __init__(self):
        self.calls = []
        self._find_result = None

    def insert_event(self, calendar_id, body):
        self.calls.append(("insert", calendar_id))
        return {"id": "g-new"}

    def patch_event(self, calendar_id, event_id, body):
        self.calls.append(("patch", calendar_id, event_id))
        return {"id": event_id}

    def delete_event(self, calendar_id, event_id):
        self.calls.append(("delete", calendar_id, event_id))

    def find_event_by_private_property(self, calendar_id, key, value):
        self.calls.append(("find", calendar_id, key, value))
        return self._find_result

    def list_all_events(self, calendar_id, time_min, time_max):
        return self._all_events


# --- adopt-don't-duplicate (find_event_by_private_property) ----------------------------------------


def test_push_adopts_existing_google_event_when_mapping_lost(mocker):
    """When local mapping is missing but Google has an event with the appt ID, adopt it."""
    _mock_model(mocker, existing=None)
    fake = FakeClient()
    fake._find_result = {"id": "g-existing"}
    service = SyncService(VALID_SA, client_factory=lambda cal: fake)

    mapping = service.push("cal@x", _snapshot())

    # Should patch the existing event, not insert a new one
    assert ("find", "cal@x", "canvasApptId", "appt-1") in fake.calls
    assert ("patch", "cal@x", "g-existing") in fake.calls
    assert ("insert", "cal@x") not in fake.calls


def test_push_inserts_when_no_google_event_found(mocker):
    """When mapping is missing AND Google has no matching event, insert fresh."""
    _mock_model(mocker, existing=None)
    fake = FakeClient()
    fake._find_result = None
    service = SyncService(VALID_SA, client_factory=lambda cal: fake)

    service.push("cal@x", _snapshot())

    assert ("find", "cal@x", "canvasApptId", "appt-1") in fake.calls
    assert ("insert", "cal@x") in fake.calls


# --- mapping cache -------------------------------------------------------------------------------


def test_push_uses_mapping_cache_hit(mocker):
    """When mapping_cache is provided and has the key, skip the DB lookup entirely."""
    model = _mock_model(mocker, existing=None)
    existing = SimpleNamespace(
        google_calendar_id="cal@x",
        google_event_id="g-1",
        last_pushed_hash="old",
        save=mocker.Mock(),
    )
    cache = {"appt-1": existing}
    fake = FakeClient()
    service = SyncService(VALID_SA, client_factory=lambda cal: fake)

    service.push("cal@x", _snapshot(), mapping_cache=cache)

    # Should NOT call .get on the model (cache used instead)
    model.objects.get.assert_not_called()
    assert ("patch", "cal@x", "g-1") in fake.calls


def test_push_uses_mapping_cache_miss(mocker):
    """When mapping_cache is provided but key is absent, treat as no mapping (authoritative)."""
    model = _mock_model(mocker, existing=None)
    cache = {}  # empty cache = authoritative miss
    fake = FakeClient()
    fake._find_result = None
    service = SyncService(VALID_SA, client_factory=lambda cal: fake)

    service.push("cal@x", _snapshot(), mapping_cache=cache)

    # Should NOT call .get — the cache miss is authoritative
    model.objects.get.assert_not_called()
    assert ("insert", "cal@x") in fake.calls


def test_resolve_mapping_without_cache_queries_db(mocker):
    existing = SimpleNamespace(
        google_calendar_id="cal@x",
        google_event_id="g-1",
        last_pushed_hash="old",
        save=mocker.Mock(),
    )
    model = _mock_model(mocker, existing=existing)
    fake = FakeClient()
    service = SyncService(VALID_SA, client_factory=lambda cal: fake)

    service.push("cal@x", _snapshot())

    model.objects.get.assert_called_once_with(canvas_appointment_id="appt-1")


# --- sweep_calendar -------------------------------------------------------------------------------


def test_sweep_calendar_removes_orphans(mocker):
    _mock_model(mocker)
    model = mocker.patch("gcal_sync.sync_service.AppointmentEventMapping")
    model.objects.filter.return_value.delete.return_value = None

    fake = FakeClient()
    fake._all_events = [
        {"id": "g1", "extendedProperties": {"private": {"canvasApptId": "orphan-1"}}},
        {"id": "g2", "extendedProperties": {"private": {"canvasApptId": "live-1"}}},
    ]
    service = SyncService(VALID_SA, client_factory=lambda cal: fake)

    deleted = service.sweep_calendar(
        "cal@x",
        live_appointment_ids={"live-1"},
        time_min="2026-01-01T00:00:00Z",
        time_max="2027-01-01T00:00:00Z",
        max_deletes=100,
    )

    assert deleted == 1
    assert ("delete", "cal@x", "g1") in fake.calls
    # live-1 is in the live set, so g2 is not deleted
    assert ("delete", "cal@x", "g2") not in fake.calls


def test_sweep_calendar_deduplicates(mocker):
    model = mocker.patch("gcal_sync.sync_service.AppointmentEventMapping")
    model.objects.filter.return_value.first.return_value = SimpleNamespace(
        google_event_id="g1"  # g1 is the mapped event
    )

    fake = FakeClient()
    fake._all_events = [
        {"id": "g1", "extendedProperties": {"private": {"canvasApptId": "live-1"}}},
        {"id": "g2", "extendedProperties": {"private": {"canvasApptId": "live-1"}}},
    ]
    service = SyncService(VALID_SA, client_factory=lambda cal: fake)

    deleted = service.sweep_calendar(
        "cal@x",
        live_appointment_ids={"live-1"},
        time_min="2026-01-01T00:00:00Z",
        time_max="2027-01-01T00:00:00Z",
        max_deletes=100,
    )

    assert deleted == 1
    # g1 is kept (the mapped event), g2 is deleted (the duplicate)
    assert ("delete", "cal@x", "g2") in fake.calls
    assert ("delete", "cal@x", "g1") not in fake.calls


def test_sweep_calendar_dedup_no_mapping_keeps_first(mocker):
    model = mocker.patch("gcal_sync.sync_service.AppointmentEventMapping")
    model.objects.filter.return_value.first.return_value = None  # no mapping

    fake = FakeClient()
    fake._all_events = [
        {"id": "g1", "extendedProperties": {"private": {"canvasApptId": "live-1"}}},
        {"id": "g2", "extendedProperties": {"private": {"canvasApptId": "live-1"}}},
    ]
    service = SyncService(VALID_SA, client_factory=lambda cal: fake)

    deleted = service.sweep_calendar(
        "cal@x",
        live_appointment_ids={"live-1"},
        time_min="2026-01-01T00:00:00Z",
        time_max="2027-01-01T00:00:00Z",
        max_deletes=100,
    )

    # First event kept, second deleted
    assert deleted == 1
    assert ("delete", "cal@x", "g2") in fake.calls


def test_sweep_calendar_respects_max_deletes(mocker):
    mocker.patch("gcal_sync.sync_service.AppointmentEventMapping")

    fake = FakeClient()
    fake._all_events = [
        {"id": f"g{i}", "extendedProperties": {"private": {"canvasApptId": f"orphan-{i}"}}}
        for i in range(10)
    ]
    service = SyncService(VALID_SA, client_factory=lambda cal: fake)

    deleted = service.sweep_calendar(
        "cal@x",
        live_appointment_ids=set(),  # all are orphans
        time_min="2026-01-01T00:00:00Z",
        time_max="2027-01-01T00:00:00Z",
        max_deletes=3,
    )

    assert deleted == 3


def test_sweep_calendar_skips_unstamped_events(mocker):
    mocker.patch("gcal_sync.sync_service.AppointmentEventMapping")

    fake = FakeClient()
    fake._all_events = [
        {"id": "g1"},  # no canvasApptId -> not ours
        {"id": "g2", "extendedProperties": {"private": {}}},  # no canvasApptId
    ]
    service = SyncService(VALID_SA, client_factory=lambda cal: fake)

    deleted = service.sweep_calendar(
        "cal@x",
        live_appointment_ids=set(),
        time_min="2026-01-01T00:00:00Z",
        time_max="2027-01-01T00:00:00Z",
        max_deletes=100,
    )

    assert deleted == 0


# --- push self-heal 410 --------------------------------------------------------------------------


def test_push_self_heals_on_410(mocker):
    existing = SimpleNamespace(
        google_calendar_id="cal@x",
        google_event_id="g-1",
        last_pushed_hash="old",
        save=mocker.Mock(),
    )
    _mock_model(mocker, existing=existing)

    class GoneClient(FakeClient):
        def patch_event(self, calendar_id, event_id, body):
            raise GoogleApiError(410, "gone")

    fake = GoneClient()
    service = SyncService(VALID_SA, client_factory=lambda cal: fake)
    service.push("cal@x", _snapshot())

    assert ("insert", "cal@x") in fake.calls
    assert existing.google_event_id == "g-new"


# --- push re-raises non-404/410 errors ---


def test_push_reraises_500(mocker):
    existing = SimpleNamespace(
        google_calendar_id="cal@x",
        google_event_id="g-1",
        last_pushed_hash="old",
        save=mocker.Mock(),
    )
    _mock_model(mocker, existing=existing)

    class ErrorClient(FakeClient):
        def patch_event(self, calendar_id, event_id, body):
            raise GoogleApiError(500, "server error")

    fake = ErrorClient()
    service = SyncService(VALID_SA, client_factory=lambda cal: fake)
    with pytest.raises(GoogleApiError):
        service.push("cal@x", _snapshot())
