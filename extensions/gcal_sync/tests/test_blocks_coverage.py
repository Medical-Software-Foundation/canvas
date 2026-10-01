"""Tests for blocks.py: block_snapshot edge cases, _upsert self-heal, sync_all_blocks error handling."""

from datetime import datetime, timezone
from types import SimpleNamespace

from gcal_sync.blocks import BlockSync, block_snapshot, sync_all_blocks
from gcal_sync.google.client import GoogleApiError


SECRETS = {"GOOGLE_SERVICE_ACCOUNT_JSON": '{"client_email": "svc@x.iam", "private_key": "KEY"}'}


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


def _event(event_id="e1", title="Lunch", ends_at=None):
    return SimpleNamespace(
        id=event_id,
        title=title,
        starts_at=datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc),
        ends_at=ends_at or datetime(2026, 6, 10, 13, 0, tzinfo=timezone.utc),
    )


# --- block_snapshot edge case: None title ----------------------------------------------------------


def test_block_snapshot_none_title():
    event = SimpleNamespace(
        id="e1",
        title=None,
        starts_at=datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 6, 10, 13, 0, tzinfo=timezone.utc),
    )
    snap = block_snapshot(event)
    assert snap["visit_type"] == "Blocked"


def test_block_snapshot_no_end_defaults_30():
    event = SimpleNamespace(
        id="e1",
        title="PTO",
        starts_at=datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc),
        ends_at=None,
    )
    snap = block_snapshot(event)
    assert snap["duration_minutes"] == 30


# --- _upsert self-heal: patch 404 -> re-insert ---------------------------------------------------


def test_upsert_self_heals_on_404(mocker):
    model = mocker.patch("gcal_sync.blocks.CalendarEventMapping")
    existing = SimpleNamespace(
        google_calendar_id="cal@x",
        google_event_id="g-1",
        last_pushed_hash="stale",
        save=mocker.Mock(),
    )

    class Client404(FakeClient):
        def patch_event(self, calendar_id, event_id, body):
            raise GoogleApiError(404, "not found")

    sync = BlockSync(SECRETS, client_factory=lambda cal: FakeClient())
    fake = Client404()
    stats = {"pushed": 0, "deleted": 0}
    sync._upsert(fake, "cal@x", "e1", _event(), stats, {"e1": existing})
    # Re-insert after 404
    assert ("insert", "cal@x") in fake.calls
    assert existing.google_event_id == "g-new"
    assert stats["pushed"] == 1


def test_upsert_self_heals_on_410(mocker):
    model = mocker.patch("gcal_sync.blocks.CalendarEventMapping")
    existing = SimpleNamespace(
        google_calendar_id="cal@x",
        google_event_id="g-1",
        last_pushed_hash="stale",
        save=mocker.Mock(),
    )

    class Client410(FakeClient):
        def patch_event(self, calendar_id, event_id, body):
            raise GoogleApiError(410, "gone")

    sync = BlockSync(SECRETS, client_factory=lambda cal: FakeClient())
    fake = Client410()
    stats = {"pushed": 0, "deleted": 0}
    sync._upsert(fake, "cal@x", "e1", _event(), stats, {"e1": existing})
    assert ("insert", "cal@x") in fake.calls
    assert stats["pushed"] == 1


# --- sync_all_blocks error handling ---------------------------------------------------------------


def test_sync_all_blocks_catches_per_provider_error(mocker):
    mocker.patch("gcal_sync.blocks.GoogleAuth")
    mocker.patch("gcal_sync.blocks.GoogleCalendarClient")
    block_sync = mocker.patch("gcal_sync.blocks.BlockSync")
    block_sync.return_value.sync_provider.side_effect = GoogleApiError(500, "boom")
    mapping = SimpleNamespace(canvas_staff_id="14", google_calendar_id="c1")
    totals = sync_all_blocks({}, [mapping])
    assert totals["pushed"] == 0
    assert totals["deleted"] == 0


def test_sync_all_blocks_aggregates_stats(mocker):
    mocker.patch("gcal_sync.blocks.GoogleAuth")
    mocker.patch("gcal_sync.blocks.GoogleCalendarClient")
    block_sync = mocker.patch("gcal_sync.blocks.BlockSync")
    block_sync.return_value.sync_provider.return_value = {"pushed": 2, "deleted": 1}
    mappings = [
        SimpleNamespace(canvas_staff_id="14", google_calendar_id="c1"),
        SimpleNamespace(canvas_staff_id="15", google_calendar_id="c2"),
    ]
    totals = sync_all_blocks({}, mappings)
    assert totals["pushed"] == 4
    assert totals["deleted"] == 2
