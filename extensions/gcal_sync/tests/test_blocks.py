"""Tests for admin-block (Calendar Event) sync: title exclusion, snapshot, upsert/delete routing."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from gcal_sync.blocks import BlockSync, block_snapshot, excluded_block_titles
from gcal_sync.google.event_builder import build_event_body, content_hash

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


def _event(event_id="e1", title="Lunch"):
    return SimpleNamespace(
        id=event_id,
        title=title,
        starts_at=datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 6, 10, 13, 0, tzinfo=timezone.utc),
    )


def _sync(mocker):
    return BlockSync(SECRETS, client_factory=lambda cal: FakeClient())


# --- title exclusion + snapshot -----------------------------------------------------------------

def test_excluded_titles_default():
    assert excluded_block_titles({}) == {"Buffer", "Lead Time"}


def test_excluded_titles_from_secret():
    assert excluded_block_titles({"EXCLUDED_BLOCK_TITLES": "Buffer, Lead Time , Hold"}) == {
        "Buffer",
        "Lead Time",
        "Hold",
    }


def test_block_snapshot_uses_title_and_duration_no_link():
    snap = block_snapshot(_event(title="PTO"))
    assert snap["visit_type"] == "PTO"
    assert snap["duration_minutes"] == 60
    assert snap["meeting_link"] is None


def test_block_snapshot_defaults_blank_title():
    snap = block_snapshot(_event(title=""))
    assert snap["visit_type"] == "Blocked"


# --- upsert routing -----------------------------------------------------------------------------

def test_upsert_inserts_when_no_mapping(mocker):
    model = mocker.patch("gcal_sync.blocks.CalendarEventMapping")
    sync = _sync(mocker)
    fake = FakeClient()
    stats = {"pushed": 0, "deleted": 0}
    sync._upsert(fake, "cal@x", "e1", _event(), stats, {})  # empty cache -> no mapping -> insert
    assert ("insert", "cal@x") in fake.calls
    model.objects.create.assert_called_once()
    assert stats["pushed"] == 1


def test_upsert_skips_when_unchanged(mocker):
    event = _event()
    unchanged_hash = content_hash(build_event_body(block_snapshot(event)))
    existing = SimpleNamespace(
        google_calendar_id="cal@x", google_event_id="g-1", last_pushed_hash=unchanged_hash
    )
    sync = _sync(mocker)
    fake = FakeClient()
    stats = {"pushed": 0, "deleted": 0}
    sync._upsert(fake, "cal@x", "e1", event, stats, {"e1": existing})
    assert fake.calls == []  # no Google call when nothing changed
    assert stats["pushed"] == 0


def test_upsert_patches_when_changed(mocker):
    existing = SimpleNamespace(
        google_calendar_id="cal@x",
        google_event_id="g-1",
        last_pushed_hash="stale",
        save=mocker.Mock(),
    )
    sync = _sync(mocker)
    fake = FakeClient()
    stats = {"pushed": 0, "deleted": 0}
    sync._upsert(fake, "cal@x", "e1", _event(), stats, {"e1": existing})
    assert ("patch", "cal@x", "g-1") in fake.calls
    assert stats["pushed"] == 1


# --- delete-removed -----------------------------------------------------------------------------

def test_delete_removed_deletes_blocks_no_longer_present(mocker):
    gone = SimpleNamespace(canvas_event_id="old", google_event_id="g-old", delete=mocker.Mock())
    kept = SimpleNamespace(canvas_event_id="cur", google_event_id="g-cur", delete=mocker.Mock())
    model = mocker.patch("gcal_sync.blocks.CalendarEventMapping")
    model.objects.filter.return_value = [gone, kept]
    sync = _sync(mocker)
    fake = FakeClient()
    stats = {"pushed": 0, "deleted": 0}
    sync._delete_removed(fake, "cal@x", {"cur"}, stats)
    assert ("delete", "cal@x", "g-old") in fake.calls
    gone.delete.assert_called_once()
    kept.delete.assert_not_called()
    assert stats["deleted"] == 1
