import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from canvas_sdk.effects import EffectType

from external_calendar_busy_blocks.sync.cron import SyncCron

_CREATE = EffectType.CALENDAR__EVENT__CREATE
_UPDATE = EffectType.CALENDAR__EVENT__UPDATE
_DELETE = EffectType.CALENDAR__EVENT__DELETE
_CALENDAR_TYPES = {_CREATE, _UPDATE, _DELETE}
_CAL_CREATE = EffectType.CALENDAR__CREATE


def _future_dt(days: int, hour: int) -> datetime:
    """A UTC datetime `days` ahead at `hour`:00, inside the 90-day look-ahead.

    SyncCron.execute() uses the real wall-clock now(), so event dates must be
    relative to now — hardcoded calendar dates rot into the past and get
    filtered out by the parser.
    """
    base = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return (base + timedelta(days=days)).replace(hour=hour)


def _z(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%SZ")


def _new_cron(timestamp: datetime, secrets: dict | None = None) -> SyncCron:
    """Construct SyncCron with a CRON event keyed to `timestamp`."""
    event = MagicMock()
    event.target.id = timestamp.isoformat()
    cron = SyncCron(event=event, secrets=secrets or {})
    cron.SCHEDULE = "*/15 * * * *"
    return cron


def _stub_feed(staff_id: str = "staff-abc", ics_url: str = "https://x.com/x.ics", **kw):
    defaults = dict(
        dbid="feed-1",
        staff_id=staff_id,
        ics_url=ics_url,
        is_active=True,
        last_etag=None,
        last_modified=None,
    )
    defaults.update(kw)
    feed = MagicMock(**defaults)
    # StaffCalendarFeed (a CustomModel) has no `id` — its PK is `dbid`. Make the
    # stub raise on `.id` like the real model so any feed.id access fails the
    # test instead of silently passing on a MagicMock auto-attribute.
    del feed.id
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
    """Patch SyncCron's external dependencies in a single place.

    `busy_ids_by_time` stands in for the live Admin calendar: tests set its
    return value to `{(starts_at, ends_at): [real_uuid, ...]}` to describe the
    blocks currently on the calendar. It defaults to an empty calendar.
    """
    with (
        patch("external_calendar_busy_blocks.sync.cron.StaffCalendarFeed") as MockFeed,
        patch("external_calendar_busy_blocks.sync.cron.busy_ids_by_time") as mock_busy,
        patch("external_calendar_busy_blocks.sync.cron.fetch_feed") as mock_fetch,
        patch(
            "external_calendar_busy_blocks.sync.cron.get_admin_calendar_id"
        ) as mock_get_cal,
    ):
        mock_get_cal.return_value = ("cal-1", [])
        mock_busy.return_value = {}
        yield {
            "feed_model": MockFeed,
            "busy": mock_busy,
            "fetch": mock_fetch,
            "get_cal": mock_get_cal,
        }


def test_new_event_emits_create_effect(patch_sync_deps) -> None:
    from external_calendar_busy_blocks.http.fetcher import FetchOk

    feed = _stub_feed()
    patch_sync_deps["feed_model"].objects.filter.return_value = [feed]
    patch_sync_deps["fetch"].return_value = FetchOk(
        body=_ok_body("ev-1@x", _z(_future_dt(10, 14)), _z(_future_dt(10, 15))),
        etag='"abc"',
        last_modified="Mon, 01 Jun 2026",
    )

    effects = _new_cron(datetime(2026, 6, 1, 14, 15, tzinfo=timezone.utc)).execute()
    create_effects = [e for e in effects if e.type == _CREATE]
    assert len(create_effects) == 1
    payload = json.loads(create_effects[0].payload)["data"]
    assert payload["title"] == "Busy"
    assert payload["calendar_id"] == "cal-1"
    # The create no longer supplies an event_id: the interpreter assigns its own
    # (KOALA-6372), so we stop pretending to control it.
    assert payload["event_id"] is None


def test_unchanged_event_emits_no_effect(patch_sync_deps) -> None:
    from external_calendar_busy_blocks.http.fetcher import FetchOk

    feed = _stub_feed()
    start = _future_dt(10, 14)
    end = _future_dt(10, 15)
    # The block is already live at this exact time; the feed wants the same.
    patch_sync_deps["feed_model"].objects.filter.return_value = [feed]
    patch_sync_deps["busy"].return_value = {(start, end): ["real-1"]}
    patch_sync_deps["fetch"].return_value = FetchOk(
        body=_ok_body("ev-1@x", _z(start), _z(end)),
        etag='"abc"',
        last_modified=None,
    )

    effects = _new_cron(datetime(2026, 6, 1, 14, 15, tzinfo=timezone.utc)).execute()
    calendar_effects = [e for e in effects if e.type in _CALENDAR_TYPES]
    assert calendar_effects == []


def test_time_changed_emits_delete_old_and_create_new(patch_sync_deps) -> None:
    # A moved meeting is a delete of the old block plus a create of the new one.
    # (The old id-based in-place UPDATE never worked — update by the stored id
    # raised "Event does not exist" under KOALA-6372.)
    from external_calendar_busy_blocks.http.fetcher import FetchOk

    feed = _stub_feed()
    old_start = _future_dt(10, 14)
    old_end = _future_dt(10, 15)
    patch_sync_deps["feed_model"].objects.filter.return_value = [feed]
    patch_sync_deps["busy"].return_value = {(old_start, old_end): ["real-old"]}
    patch_sync_deps["fetch"].return_value = FetchOk(
        body=_ok_body("ev-1@x", _z(_future_dt(10, 16)), _z(_future_dt(10, 17))),
        etag=None,
        last_modified=None,
    )

    effects = _new_cron(datetime(2026, 6, 1, 14, 15, tzinfo=timezone.utc)).execute()
    delete_effects = [e for e in effects if e.type == _DELETE]
    create_effects = [e for e in effects if e.type == _CREATE]
    update_effects = [e for e in effects if e.type == _UPDATE]
    assert len(delete_effects) == 1
    assert len(create_effects) == 1
    assert update_effects == []
    # The delete carried the REAL uuid read off the calendar, not a stored id.
    assert json.loads(delete_effects[0].payload)["data"]["event_id"] == "real-old"


def test_orphan_block_deleted_by_real_uuid(patch_sync_deps) -> None:
    # The self-heal: a live block the feed no longer contains is deleted by its
    # real uuid, while the block the feed still wants is left untouched.
    from external_calendar_busy_blocks.http.fetcher import FetchOk

    feed = _stub_feed()
    keep_start, keep_end = _future_dt(10, 14), _future_dt(10, 15)
    orphan_start, orphan_end = _future_dt(20, 9), _future_dt(20, 21)
    patch_sync_deps["feed_model"].objects.filter.return_value = [feed]
    patch_sync_deps["busy"].return_value = {
        (keep_start, keep_end): ["real-keep"],
        (orphan_start, orphan_end): ["real-orphan"],
    }
    patch_sync_deps["fetch"].return_value = FetchOk(
        body=_ok_body("ev-keep@x", _z(keep_start), _z(keep_end)),
        etag=None,
        last_modified=None,
    )

    effects = _new_cron(datetime(2026, 6, 1, 14, 15, tzinfo=timezone.utc)).execute()
    delete_effects = [e for e in effects if e.type == _DELETE]
    create_effects = [e for e in effects if e.type == _CREATE]
    assert create_effects == []
    assert len(delete_effects) == 1
    assert json.loads(delete_effects[0].payload)["data"]["event_id"] == "real-orphan"


def test_duplicate_blocks_pruned_to_feed_count(patch_sync_deps) -> None:
    # The triplicate case: the feed wants one block at a time, three are live;
    # two are deleted and one is kept. No creates.
    from external_calendar_busy_blocks.http.fetcher import FetchOk

    feed = _stub_feed()
    start, end = _future_dt(15, 10), _future_dt(15, 11)
    patch_sync_deps["feed_model"].objects.filter.return_value = [feed]
    patch_sync_deps["busy"].return_value = {(start, end): ["dup-1", "dup-2", "dup-3"]}
    patch_sync_deps["fetch"].return_value = FetchOk(
        body=_ok_body("ev-1@x", _z(start), _z(end)),
        etag=None,
        last_modified=None,
    )

    effects = _new_cron(datetime(2026, 6, 1, 14, 15, tzinfo=timezone.utc)).execute()
    delete_effects = [e for e in effects if e.type == _DELETE]
    create_effects = [e for e in effects if e.type == _CREATE]
    assert create_effects == []
    assert len(delete_effects) == 2
    deleted_ids = {json.loads(e.payload)["data"]["event_id"] for e in delete_effects}
    # Exactly one of the three real uuids is kept.
    assert deleted_ids.issubset({"dup-1", "dup-2", "dup-3"})
    assert len(deleted_ids) == 2


def test_delete_cap_limits_deletes_per_tick(patch_sync_deps) -> None:
    # The safety valve: with a cap of 2, only two of several orphans are deleted
    # this tick; the rest clear on later ticks. The feed's own block still needs
    # creating (creates are not capped).
    from external_calendar_busy_blocks.http.fetcher import FetchOk

    feed = _stub_feed()
    wanted_start, wanted_end = _future_dt(5, 8), _future_dt(5, 9)
    orphans = {
        (_future_dt(6, 9), _future_dt(6, 10)): ["orph-1"],
        (_future_dt(7, 9), _future_dt(7, 10)): ["orph-2"],
        (_future_dt(8, 9), _future_dt(8, 10)): ["orph-3"],
        (_future_dt(9, 9), _future_dt(9, 10)): ["orph-4"],
    }
    patch_sync_deps["feed_model"].objects.filter.return_value = [feed]
    patch_sync_deps["busy"].return_value = orphans
    patch_sync_deps["fetch"].return_value = FetchOk(
        body=_ok_body("ev-want@x", _z(wanted_start), _z(wanted_end)),
        etag=None,
        last_modified=None,
    )

    cron = _new_cron(
        datetime(2026, 6, 1, 14, 15, tzinfo=timezone.utc),
        secrets={"MAX_DELETES_PER_SYNC": "2"},
    )
    effects = cron.execute()
    delete_effects = [e for e in effects if e.type == _DELETE]
    create_effects = [e for e in effects if e.type == _CREATE]
    assert len(delete_effects) == 2  # capped
    assert len(create_effects) == 1  # the wanted block is created regardless


def test_safety_guard_skips_deletes_on_empty_feed(patch_sync_deps) -> None:
    # A feed that parses to zero events while blocks are still live is treated as
    # a transient glitch: deletions are skipped rather than wiping the calendar.
    from external_calendar_busy_blocks.http.fetcher import FetchOk

    feed = _stub_feed()
    start, end = _future_dt(15, 14), _future_dt(15, 15)
    patch_sync_deps["feed_model"].objects.filter.return_value = [feed]
    patch_sync_deps["busy"].return_value = {(start, end): ["real-1"]}
    patch_sync_deps["fetch"].return_value = FetchOk(
        body=b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n",
        etag=None,
        last_modified=None,
    )

    effects = _new_cron(datetime(2026, 6, 1, 14, 15, tzinfo=timezone.utc)).execute()
    delete_effects = [e for e in effects if e.type == _DELETE]
    assert delete_effects == []
    assert feed.last_error and "empty" in feed.last_error.lower()


def test_304_emits_no_effects(patch_sync_deps) -> None:
    from external_calendar_busy_blocks.http.fetcher import NotModified

    feed = _stub_feed(last_etag='"abc"')
    patch_sync_deps["feed_model"].objects.filter.return_value = [feed]
    patch_sync_deps["fetch"].return_value = NotModified()

    effects = _new_cron(datetime(2026, 6, 1, 14, 15, tzinfo=timezone.utc)).execute()
    calendar_effects = [e for e in effects if e.type in _CALENDAR_TYPES]
    assert calendar_effects == []
    # A 304 never reads the live calendar (nothing to reconcile against).
    patch_sync_deps["busy"].assert_not_called()


def test_401_deactivates_feed(patch_sync_deps) -> None:
    from external_calendar_busy_blocks.http.fetcher import Unauthorized

    feed = _stub_feed()
    patch_sync_deps["feed_model"].objects.filter.return_value = [feed]
    patch_sync_deps["fetch"].return_value = Unauthorized()

    _new_cron(datetime(2026, 6, 1, 14, 15, tzinfo=timezone.utc)).execute()
    assert feed.is_active is False
    assert feed.save.called


def test_5xx_keeps_feed_active(patch_sync_deps) -> None:
    from external_calendar_busy_blocks.http.fetcher import TransientError

    feed = _stub_feed()
    patch_sync_deps["feed_model"].objects.filter.return_value = [feed]
    patch_sync_deps["fetch"].return_value = TransientError(reason="HTTP 503")

    _new_cron(datetime(2026, 6, 1, 14, 15, tzinfo=timezone.utc)).execute()
    assert feed.is_active is True
    assert feed.last_error == "HTTP 503"


def test_no_admin_calendar_records_error_and_skips(patch_sync_deps) -> None:
    feed = _stub_feed()
    patch_sync_deps["feed_model"].objects.filter.return_value = [feed]
    patch_sync_deps["get_cal"].return_value = ("", [])

    effects = _new_cron(datetime(2026, 6, 1, 14, 15, tzinfo=timezone.utc)).execute()
    assert effects == []
    assert feed.last_error and "unable to provision" in feed.last_error.lower()


def test_live_calendar_read_within_lookahead_window(patch_sync_deps) -> None:
    # Regression: the live-calendar read must be bounded to the same window the
    # parser covers ([now, now + lookahead]), so far-future blocks the feed has
    # not yielded yet are never treated as orphans and deleted.
    from external_calendar_busy_blocks.http.fetcher import FetchOk

    now = datetime(2026, 6, 1, 14, 15, tzinfo=timezone.utc)
    feed = _stub_feed()
    patch_sync_deps["feed_model"].objects.filter.return_value = [feed]
    patch_sync_deps["fetch"].return_value = FetchOk(
        body=_ok_body("ev-1@x", _z(_future_dt(10, 14)), _z(_future_dt(10, 15))),
        etag=None,
        last_modified=None,
    )

    _new_cron(now).execute()

    # busy_ids_by_time(calendar_id, now, window_end) with a tz-aware window_end
    # ~90 days out. The cron uses its own wall-clock now, so assert relative.
    args, _ = patch_sync_deps["busy"].call_args
    calendar_id, call_now, window_end = args
    assert calendar_id == "cal-1"
    assert call_now.tzinfo is not None
    assert window_end.tzinfo is not None
    assert timedelta(days=89) < (window_end - call_now) < timedelta(days=91)


def test_one_feed_failure_does_not_abort_other_feeds(patch_sync_deps) -> None:
    # A per-feed isolation backstop: if syncing one feed raises an unexpected
    # exception, the cron must record the error, skip that feed, and continue
    # syncing the others — not abort the whole tick.
    from external_calendar_busy_blocks.http.fetcher import FetchOk

    feed_a = _stub_feed(staff_id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", ics_url="https://a/x.ics")
    feed_b = _stub_feed(staff_id="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", ics_url="https://b/x.ics")
    patch_sync_deps["feed_model"].objects.filter.return_value = [feed_a, feed_b]

    # Feed A blows up unexpectedly; Feed B returns a valid single event.
    def fetch_side_effect(url, etag, last_modified):
        if url == "https://a/x.ics":
            raise RuntimeError("unexpected boom")
        return FetchOk(
            body=_ok_body("ev-b@x", _z(_future_dt(10, 14)), _z(_future_dt(10, 15))),
            etag=None,
            last_modified=None,
        )

    patch_sync_deps["fetch"].side_effect = fetch_side_effect

    effects = _new_cron(datetime(2026, 6, 1, 14, 15, tzinfo=timezone.utc)).execute()

    # Feed B's create effect still emitted despite feed A blowing up.
    create_effects = [e for e in effects if e.type == _CREATE]
    assert len(create_effects) == 1
    # Feed A recorded an error and was saved.
    assert feed_a.last_error and "unexpected" in feed_a.last_error.lower()
    assert feed_a.save.called


def test_new_calendar_effect_is_prepended_before_events(patch_sync_deps) -> None:
    from external_calendar_busy_blocks.http.fetcher import FetchOk

    cal_effect = MagicMock()
    cal_effect.type = _CAL_CREATE
    patch_sync_deps["get_cal"].return_value = ("cal-9", [cal_effect])

    feed = _stub_feed()
    patch_sync_deps["feed_model"].objects.filter.return_value = [feed]
    patch_sync_deps["fetch"].return_value = FetchOk(
        body=_ok_body("ev-1@x", _z(_future_dt(10, 14)), _z(_future_dt(10, 15))),
        etag=None,
        last_modified=None,
    )

    effects = _new_cron(datetime(2026, 6, 1, 14, 15, tzinfo=timezone.utc)).execute()
    # Calendar create must come first, before the Event.create that references it.
    assert effects[0] is cal_effect
    create_effects = [e for e in effects if e.type == _CREATE]
    assert len(create_effects) == 1
    payload = json.loads(create_effects[0].payload)["data"]
    assert payload["calendar_id"] == "cal-9"


def test_not_modified_still_provisions_missing_calendar(patch_sync_deps) -> None:
    from external_calendar_busy_blocks.http.fetcher import NotModified

    cal_effect = MagicMock()
    cal_effect.type = _CAL_CREATE
    patch_sync_deps["get_cal"].return_value = ("cal-9", [cal_effect])

    feed = _stub_feed(last_etag='"abc"')
    patch_sync_deps["feed_model"].objects.filter.return_value = [feed]
    patch_sync_deps["fetch"].return_value = NotModified()

    effects = _new_cron(datetime(2026, 6, 1, 14, 15, tzinfo=timezone.utc)).execute()
    assert effects == [cal_effect]
