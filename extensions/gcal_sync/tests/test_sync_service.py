"""Tests for SyncService push/remove routing, using a fake Google client and a mocked mapping model.

These exercise the decision logic (insert vs patch, self-heal on a deleted event, calendar re-map,
delete) without a database or live Google calls.
"""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from gcal_sync.google.client import GoogleApiError
from gcal_sync.sync_service import SyncService

VALID_SA = '{"client_email": "svc@x.iam", "private_key": "KEY"}'


def _snapshot():
    return {
        "appointment_id": "appt-1",
        "visit_type": "Visit",
        "start_time": datetime(2026, 6, 10, 15, 0, tzinfo=timezone.utc),
        "duration_minutes": 30,
        "location": "Clinic",
        "meeting_link": None,
        "status": "confirmed",
    }


class FakeClient:
    def __init__(self, find_result=None):
        self.calls = []
        # What find_event_by_private_property returns: an event dict to adopt, or None.
        self.find_result = find_result
        # What list_all_events returns (set per-test for sweep coverage).
        self.all_events = []

    def insert_event(self, calendar_id, body):
        self.calls.append(("insert", calendar_id))
        return {"id": "g-new"}

    def patch_event(self, calendar_id, event_id, body):
        self.calls.append(("patch", calendar_id, event_id))
        return {"id": event_id}

    def delete_event(self, calendar_id, event_id):
        self.calls.append(("delete", calendar_id, event_id))

    def find_event_by_private_property(self, calendar_id, key, value):
        self.calls.append(("find", calendar_id, value))
        return self.find_result

    def list_all_events(self, calendar_id, time_min, time_max):
        self.calls.append(("list_all", calendar_id))
        return getattr(self, "all_events", [])


def _mock_model(mocker, existing):
    """Patch AppointmentEventMapping so .get returns ``existing`` (or raises DoesNotExist if None)."""
    model = mocker.patch("gcal_sync.sync_service.AppointmentEventMapping")
    model.DoesNotExist = type("DoesNotExist", (Exception,), {})
    if existing is None:
        model.objects.get.side_effect = model.DoesNotExist
    else:
        model.objects.get.return_value = existing
    model.objects.create.side_effect = lambda **kw: SimpleNamespace(**kw)
    model.objects.update_or_create.side_effect = lambda **kw: (
        SimpleNamespace(canvas_appointment_id=kw["canvas_appointment_id"], **kw["defaults"]),
        True,
    )
    return model


def test_push_inserts_when_no_existing_mapping(mocker):
    model = _mock_model(mocker, existing=None)
    fake = FakeClient(find_result=None)  # Google has no prior event for this appointment
    service = SyncService(VALID_SA, client_factory=lambda cal: fake)

    service.push("cal@example.com", _snapshot())

    assert ("find", "cal@example.com", "appt-1") in fake.calls  # checked for an adoptable event
    assert ("insert", "cal@example.com") in fake.calls
    model.objects.update_or_create.assert_called_once()
    assert model.objects.update_or_create.call_args.kwargs["defaults"]["google_event_id"] == "g-new"


def test_push_adopts_existing_google_event_when_mapping_missing(mocker):
    # Idempotency: no local mapping, but Google already has an event we stamped with this appt id.
    # ADOPT it (patch in place) instead of inserting a DUPLICATE — the fix that makes the reconcile
    # safe to re-run after mapping drift (hard-deleted/recreated appts, dropped mapping rows).
    model = _mock_model(mocker, existing=None)
    fake = FakeClient(find_result={"id": "g-existing"})
    service = SyncService(VALID_SA, client_factory=lambda cal: fake)

    service.push("cal@example.com", _snapshot())

    assert ("find", "cal@example.com", "appt-1") in fake.calls
    assert ("patch", "cal@example.com", "g-existing") in fake.calls
    assert ("insert", "cal@example.com") not in fake.calls  # no duplicate event created
    assert model.objects.update_or_create.call_args.kwargs["defaults"]["google_event_id"] == "g-existing"


def test_push_skips_when_content_unchanged(mocker):
    # Change-only: same calendar + same content hash -> no Google call, no save (scaling fix).
    from gcal_sync.google.event_builder import build_event_body, content_hash

    snap = _snapshot()
    unchanged_hash = content_hash(build_event_body(snap))
    existing = SimpleNamespace(
        google_calendar_id="cal@example.com",
        google_event_id="g-1",
        last_pushed_hash=unchanged_hash,
        save=mocker.Mock(),
    )
    _mock_model(mocker, existing=existing)
    fake = FakeClient()
    service = SyncService(VALID_SA, client_factory=lambda cal: fake)

    service.push("cal@example.com", snap)

    assert fake.calls == []  # nothing sent to Google
    existing.save.assert_not_called()


def test_push_patches_existing_mapping_same_calendar(mocker):
    existing = SimpleNamespace(
        google_calendar_id="cal@example.com",
        google_event_id="g-1",
        last_pushed_hash="old",
        save=mocker.Mock(),
    )
    _mock_model(mocker, existing=existing)
    fake = FakeClient()
    service = SyncService(VALID_SA, client_factory=lambda cal: fake)

    service.push("cal@example.com", _snapshot())

    assert ("patch", "cal@example.com", "g-1") in fake.calls
    existing.save.assert_called_once()
    assert existing.last_pushed_hash != "old"  # hash refreshed


def test_push_self_heals_when_event_deleted_in_google(mocker):
    existing = SimpleNamespace(
        google_calendar_id="cal@example.com",
        google_event_id="g-1",
        last_pushed_hash="old",
        save=mocker.Mock(),
    )
    _mock_model(mocker, existing=existing)

    class DeletedEventClient(FakeClient):
        def patch_event(self, calendar_id, event_id, body):
            raise GoogleApiError(404, "not found")

    fake = DeletedEventClient()
    service = SyncService(VALID_SA, client_factory=lambda cal: fake)

    service.push("cal@example.com", _snapshot())

    # Patch failed with 404 -> re-create, and the mapping now points at the new event.
    assert ("insert", "cal@example.com") in fake.calls
    assert existing.google_event_id == "g-new"


def test_push_moves_event_when_calendar_changes(mocker):
    existing = SimpleNamespace(
        google_calendar_id="old@example.com",
        google_event_id="g-1",
        last_pushed_hash="old",
        save=mocker.Mock(),
    )
    _mock_model(mocker, existing=existing)
    fake = FakeClient()
    service = SyncService(VALID_SA, client_factory=lambda cal: fake)

    service.push("new@example.com", _snapshot())

    assert ("delete", "old@example.com", "g-1") in fake.calls
    assert ("insert", "new@example.com") in fake.calls
    assert existing.google_calendar_id == "new@example.com"


def test_push_uses_prefetched_mapping_cache_without_querying(mocker):
    # Batch path (reconcile): a supplied cache is authoritative -> no per-appointment .get() query.
    from gcal_sync.google.event_builder import build_event_body, content_hash

    snap = _snapshot()
    existing = SimpleNamespace(
        google_calendar_id="cal@example.com",
        google_event_id="g-1",
        last_pushed_hash=content_hash(build_event_body(snap)),  # unchanged -> no Google call
        save=mocker.Mock(),
    )
    model = _mock_model(mocker, existing=None)  # .get() would raise DoesNotExist if it were called
    fake = FakeClient()
    service = SyncService(VALID_SA, client_factory=lambda cal: fake)

    service.push("cal@example.com", snap, {"appt-1": existing})

    model.objects.get.assert_not_called()  # resolved from cache, not the DB
    assert fake.calls == []  # matching hash -> nothing sent to Google


def test_push_cache_miss_inserts_without_falling_back_to_query(mocker):
    # A cache MISS means "no mapping exists" (the cache is authoritative for its ids); push must
    # insert, NOT fall back to a query -> that fallback would re-introduce the N+1.
    should_not_use = SimpleNamespace(
        google_calendar_id="cal@example.com", google_event_id="g-1", last_pushed_hash="x"
    )
    model = _mock_model(mocker, existing=should_not_use)  # .get() returns a mapping if wrongly called
    fake = FakeClient()
    service = SyncService(VALID_SA, client_factory=lambda cal: fake)

    service.push("cal@example.com", _snapshot(), {})  # empty cache -> miss

    model.objects.get.assert_not_called()  # no fallback query
    assert ("insert", "cal@example.com") in fake.calls  # treated as new -> insert
    model.objects.update_or_create.assert_called_once()


def _ev(event_id, appt_id=None):
    priv = {"canvasApptId": appt_id} if appt_id else {}
    return {"id": event_id, "extendedProperties": {"private": priv}}


def test_sweep_deletes_orphan_events_and_drops_mapping(mocker):
    # An event we stamped whose appointment id is NOT in the live set is an orphan (appt
    # cancelled/deleted/out-of-window) -> delete the event and drop its mapping.
    model = mocker.patch("gcal_sync.sync_service.AppointmentEventMapping")
    fake = FakeClient()
    fake.all_events = [_ev("e-dead", "dead"), _ev("e-live", "live"), _ev("e-nostamp")]
    service = SyncService(VALID_SA, client_factory=lambda cal: fake)

    deleted = service.sweep_calendar("cal", {"live"}, "t0", "t1", max_deletes=100)

    assert deleted == 1
    assert ("delete", "cal", "e-dead") in fake.calls
    assert ("delete", "cal", "e-live") not in fake.calls  # live appt kept
    assert ("delete", "cal", "e-nostamp") not in fake.calls  # not ours -> never touched
    model.objects.filter.assert_any_call(canvas_appointment_id="dead", google_calendar_id="cal")


def test_sweep_collapses_duplicate_events_keeping_mapped_one(mocker):
    # Two live events for the same appointment -> keep the one the mapping points at, delete the rest.
    model = mocker.patch("gcal_sync.sync_service.AppointmentEventMapping")
    model.objects.filter.return_value.first.return_value = SimpleNamespace(google_event_id="e-keep")
    fake = FakeClient()
    fake.all_events = [_ev("e-dupe", "live"), _ev("e-keep", "live")]
    service = SyncService(VALID_SA, client_factory=lambda cal: fake)

    deleted = service.sweep_calendar("cal", {"live"}, "t0", "t1", max_deletes=100)

    assert deleted == 1
    assert ("delete", "cal", "e-dupe") in fake.calls
    assert ("delete", "cal", "e-keep") not in fake.calls


def test_sweep_respects_max_deletes(mocker):
    mocker.patch("gcal_sync.sync_service.AppointmentEventMapping")
    fake = FakeClient()
    fake.all_events = [_ev("e1", "dead1"), _ev("e2", "dead2"), _ev("e3", "dead3")]
    service = SyncService(VALID_SA, client_factory=lambda cal: fake)

    deleted = service.sweep_calendar("cal", set(), "t0", "t1", max_deletes=2)

    assert deleted == 2  # capped, not 3
    assert sum(1 for c in fake.calls if c[0] == "delete") == 2


def test_remove_deletes_event_and_mapping(mocker):
    existing = SimpleNamespace(
        google_calendar_id="cal@example.com",
        google_event_id="g-1",
        delete=mocker.Mock(),
    )
    _mock_model(mocker, existing=existing)
    fake = FakeClient()
    service = SyncService(VALID_SA, client_factory=lambda cal: fake)

    assert service.remove("appt-1") is True
    assert ("delete", "cal@example.com", "g-1") in fake.calls
    existing.delete.assert_called_once()


def test_remove_returns_false_when_no_mapping(mocker):
    _mock_model(mocker, existing=None)
    fake = FakeClient()
    service = SyncService(VALID_SA, client_factory=lambda cal: fake)
    assert service.remove("appt-unknown") is False
    assert fake.calls == []
