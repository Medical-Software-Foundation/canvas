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
    def __init__(self):
        self.calls = []

    def insert_event(self, calendar_id, body):
        self.calls.append(("insert", calendar_id))
        return {"id": "g-new"}

    def patch_event(self, calendar_id, event_id, body):
        self.calls.append(("patch", calendar_id, event_id))
        return {"id": event_id}

    def delete_event(self, calendar_id, event_id):
        self.calls.append(("delete", calendar_id, event_id))


def _mock_model(mocker, existing):
    """Patch AppointmentEventMapping so .get returns ``existing`` (or raises DoesNotExist if None)."""
    model = mocker.patch("gcal_sync.sync_service.AppointmentEventMapping")
    model.DoesNotExist = type("DoesNotExist", (Exception,), {})
    if existing is None:
        model.objects.get.side_effect = model.DoesNotExist
    else:
        model.objects.get.return_value = existing
    model.objects.create.side_effect = lambda **kw: SimpleNamespace(**kw)
    return model


def test_push_inserts_when_no_existing_mapping(mocker):
    model = _mock_model(mocker, existing=None)
    fake = FakeClient()
    service = SyncService(VALID_SA, client_factory=lambda cal: fake)

    service.push("cal@example.com", _snapshot())

    assert ("insert", "cal@example.com") in fake.calls
    model.objects.create.assert_called_once()
    assert model.objects.create.call_args.kwargs["google_event_id"] == "g-new"


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
