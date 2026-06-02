import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from canvas_sdk.effects import EffectType

from external_calendar_busy_blocks.sync.cron import SyncCron

_CREATE = EffectType.CALENDAR__EVENT__CREATE
_UPDATE = EffectType.CALENDAR__EVENT__UPDATE
_DELETE = EffectType.CALENDAR__EVENT__DELETE
_CALENDAR_TYPES = {_CREATE, _UPDATE, _DELETE}


def _new_cron(timestamp: datetime) -> SyncCron:
    """Construct SyncCron with a CRON event keyed to `timestamp`."""
    event = MagicMock()
    event.target.id = timestamp.isoformat()
    cron = SyncCron(event=event)
    cron.SCHEDULE = "*/15 * * * *"
    return cron


def _stub_feed(staff_id: str = "staff-abc", ics_url: str = "https://x.com/x.ics", **kw):
    defaults = dict(
        id="feed-1",
        staff_id=staff_id,
        ics_url=ics_url,
        is_active=True,
        last_etag=None,
        last_modified=None,
    )
    defaults.update(kw)
    feed = MagicMock(**defaults)
    return feed


def _ok_body(uid: str, start_z: str, end_z: str) -> bytes:
    return (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{uid}\r\n"
        "DTSTAMP:20260601T120000Z\r\n"
        f"DTSTART:{start_z}\r\n"
        f"DTEND:{end_z}\r\n"
        "STATUS:CONFIRMED\r\n"
        "TRANSP:OPAQUE\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    ).encode()


@pytest.fixture
def patch_sync_deps():
    """Patch SyncCron's external dependencies in a single place."""
    with (
        patch("external_calendar_busy_blocks.sync.cron.StaffCalendarFeed") as MockFeed,
        patch("external_calendar_busy_blocks.sync.cron.ImportedEvent") as MockImported,
        patch("external_calendar_busy_blocks.sync.cron.fetch_feed") as mock_fetch,
        patch("external_calendar_busy_blocks.sync.cron.Staff") as MockStaff,
        patch(
            "external_calendar_busy_blocks.sync.cron.find_admin_calendar_id"
        ) as mock_find_cal,
    ):
        MockStaff.objects.get.return_value = MagicMock(full_name="Jane Doe")
        mock_find_cal.return_value = "cal-1"
        yield {
            "feed_model": MockFeed,
            "imported_model": MockImported,
            "fetch": mock_fetch,
            "staff": MockStaff,
            "find_cal": mock_find_cal,
        }


def test_new_event_emits_create_effect(patch_sync_deps) -> None:
    from external_calendar_busy_blocks.http.fetcher import FetchOk

    feed = _stub_feed()
    patch_sync_deps["feed_model"].objects.filter.return_value = [feed]
    patch_sync_deps["imported_model"].objects.filter.return_value = []
    patch_sync_deps["fetch"].return_value = FetchOk(
        body=_ok_body("ev-1@x", "20260615T140000Z", "20260615T150000Z"),
        etag='"abc"',
        last_modified="Mon, 01 Jun 2026",
    )

    effects = _new_cron(datetime(2026, 6, 1, 14, 15, tzinfo=timezone.utc)).execute()
    create_effects = [e for e in effects if e.type == _CREATE]
    assert len(create_effects) == 1
    payload = json.loads(create_effects[0].payload)["data"]
    assert payload["title"] == "Busy"
    assert payload["calendar_id"] == "cal-1"


def test_unchanged_event_emits_no_effect(patch_sync_deps) -> None:
    from external_calendar_busy_blocks.http.fetcher import FetchOk

    feed = _stub_feed()
    existing = MagicMock(
        ics_uid="ev-1@x",
        recurrence_id=None,
        canvas_event_id="canvas-1",
        sequence=0,
        starts_at=datetime(2026, 6, 15, 14, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 6, 15, 15, 0, tzinfo=timezone.utc),
    )
    patch_sync_deps["feed_model"].objects.filter.return_value = [feed]
    patch_sync_deps["imported_model"].objects.filter.return_value = [existing]
    patch_sync_deps["fetch"].return_value = FetchOk(
        body=_ok_body("ev-1@x", "20260615T140000Z", "20260615T150000Z"),
        etag='"abc"',
        last_modified=None,
    )

    effects = _new_cron(datetime(2026, 6, 1, 14, 15, tzinfo=timezone.utc)).execute()
    calendar_effects = [e for e in effects if e.type in _CALENDAR_TYPES]
    assert calendar_effects == []


def test_time_changed_emits_update_effect(patch_sync_deps) -> None:
    from external_calendar_busy_blocks.http.fetcher import FetchOk

    feed = _stub_feed()
    existing = MagicMock(
        ics_uid="ev-1@x",
        recurrence_id=None,
        canvas_event_id="canvas-1",
        sequence=0,
        starts_at=datetime(2026, 6, 15, 14, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 6, 15, 15, 0, tzinfo=timezone.utc),
    )
    patch_sync_deps["feed_model"].objects.filter.return_value = [feed]
    patch_sync_deps["imported_model"].objects.filter.return_value = [existing]
    patch_sync_deps["fetch"].return_value = FetchOk(
        body=_ok_body("ev-1@x", "20260615T160000Z", "20260615T170000Z"),
        etag=None,
        last_modified=None,
    )

    effects = _new_cron(datetime(2026, 6, 1, 14, 15, tzinfo=timezone.utc)).execute()
    update_effects = [e for e in effects if e.type == _UPDATE]
    assert len(update_effects) == 1
    payload = json.loads(update_effects[0].payload)["data"]
    assert payload["event_id"] == "canvas-1"


def test_removed_event_emits_delete_effect(patch_sync_deps) -> None:
    from external_calendar_busy_blocks.http.fetcher import FetchOk

    feed = _stub_feed()
    existing = MagicMock(
        ics_uid="ev-old@x",
        recurrence_id=None,
        canvas_event_id="canvas-old",
        sequence=0,
        starts_at=datetime(2026, 6, 15, 14, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 6, 15, 15, 0, tzinfo=timezone.utc),
    )
    patch_sync_deps["feed_model"].objects.filter.return_value = [feed]
    patch_sync_deps["imported_model"].objects.filter.return_value = [existing]
    patch_sync_deps["fetch"].return_value = FetchOk(
        body=_ok_body("ev-new@x", "20260615T140000Z", "20260615T150000Z"),
        etag=None,
        last_modified=None,
    )

    effects = _new_cron(datetime(2026, 6, 1, 14, 15, tzinfo=timezone.utc)).execute()
    delete_effects = [e for e in effects if e.type == _DELETE]
    create_effects = [e for e in effects if e.type == _CREATE]
    assert len(delete_effects) == 1
    assert len(create_effects) == 1
    delete_payload = json.loads(delete_effects[0].payload)["data"]
    assert delete_payload["event_id"] == "canvas-old"


def test_safety_guard_skips_deletes_on_empty_feed(patch_sync_deps) -> None:
    from external_calendar_busy_blocks.http.fetcher import FetchOk

    feed = _stub_feed()
    existing = MagicMock(
        ics_uid="ev-1@x",
        recurrence_id=None,
        canvas_event_id="canvas-1",
        sequence=0,
        starts_at=datetime(2026, 6, 15, 14, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 6, 15, 15, 0, tzinfo=timezone.utc),
    )
    patch_sync_deps["feed_model"].objects.filter.return_value = [feed]
    patch_sync_deps["imported_model"].objects.filter.return_value = [existing]
    patch_sync_deps["fetch"].return_value = FetchOk(
        body=b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n",
        etag=None,
        last_modified=None,
    )

    effects = _new_cron(datetime(2026, 6, 1, 14, 15, tzinfo=timezone.utc)).execute()
    delete_effects = [e for e in effects if e.type == _DELETE]
    assert delete_effects == []


def test_304_emits_no_effects(patch_sync_deps) -> None:
    from external_calendar_busy_blocks.http.fetcher import NotModified

    feed = _stub_feed(last_etag='"abc"')
    patch_sync_deps["feed_model"].objects.filter.return_value = [feed]
    patch_sync_deps["imported_model"].objects.filter.return_value = []
    patch_sync_deps["fetch"].return_value = NotModified()

    effects = _new_cron(datetime(2026, 6, 1, 14, 15, tzinfo=timezone.utc)).execute()
    calendar_effects = [e for e in effects if e.type in _CALENDAR_TYPES]
    assert calendar_effects == []


def test_401_deactivates_feed(patch_sync_deps) -> None:
    from external_calendar_busy_blocks.http.fetcher import Unauthorized

    feed = _stub_feed()
    patch_sync_deps["feed_model"].objects.filter.return_value = [feed]
    patch_sync_deps["imported_model"].objects.filter.return_value = []
    patch_sync_deps["fetch"].return_value = Unauthorized()

    _new_cron(datetime(2026, 6, 1, 14, 15, tzinfo=timezone.utc)).execute()
    assert feed.is_active is False
    assert feed.save.called


def test_5xx_keeps_feed_active(patch_sync_deps) -> None:
    from external_calendar_busy_blocks.http.fetcher import TransientError

    feed = _stub_feed()
    patch_sync_deps["feed_model"].objects.filter.return_value = [feed]
    patch_sync_deps["imported_model"].objects.filter.return_value = []
    patch_sync_deps["fetch"].return_value = TransientError(reason="HTTP 503")

    _new_cron(datetime(2026, 6, 1, 14, 15, tzinfo=timezone.utc)).execute()
    assert feed.is_active is True
    assert feed.last_error == "HTTP 503"


def test_no_admin_calendar_records_error_and_skips(patch_sync_deps) -> None:
    feed = _stub_feed()
    patch_sync_deps["feed_model"].objects.filter.return_value = [feed]
    patch_sync_deps["imported_model"].objects.filter.return_value = []
    patch_sync_deps["find_cal"].return_value = None

    effects = _new_cron(datetime(2026, 6, 1, 14, 15, tzinfo=timezone.utc)).execute()
    assert effects == []
    assert feed.last_error and "no admin calendar" in feed.last_error.lower()
