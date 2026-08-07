from collections import Counter
from datetime import datetime, timedelta, timezone

from logger import log

from canvas_sdk.effects import Effect
from canvas_sdk.effects.calendar import Event
from canvas_sdk.handlers.cron_task import CronTask

from external_calendar_busy_blocks.calendars.admin_lookup import get_admin_calendar_id
from external_calendar_busy_blocks.calendars.live_events import busy_ids_by_time
from external_calendar_busy_blocks.data.models import StaffCalendarFeed
from external_calendar_busy_blocks.http.fetcher import (
    FetchOk,
    NotFound,
    NotModified,
    TransientError,
    Unauthorized,
    fetch_feed,
    redact_url,
)
from external_calendar_busy_blocks.ics.parser import parse_ics
from external_calendar_busy_blocks.ics.types import IcsParseError, ParsedEvent

LOOKAHEAD_DAYS_DEFAULT = 90

# Safety valve: the most block deletions a single feed may emit in one tick.
# A healthy feed deletes only what genuinely dropped out; this bounds the blast
# radius if a feed ever parses partially, and it spreads the one-time cleanup of
# historical orphans over a few ticks rather than firing hundreds of deletes at
# once. Anything left over clears on the next run.
MAX_DELETES_PER_SYNC_DEFAULT = 500


class SyncCron(CronTask):
    """Polls every 15 minutes and reconciles ICS feeds to Canvas Admin events."""

    SCHEDULE = "*/15 * * * *"

    def execute(self) -> list[Effect]:
        now = datetime.now(timezone.utc)
        lookahead = self._lookahead_days()
        max_deletes = self._max_deletes_per_sync()
        effects: list[Effect] = []

        for feed in StaffCalendarFeed.objects.filter(is_active=True):
            try:
                effects.extend(self._sync_feed(feed, now, lookahead, max_deletes))
            except Exception as exc:  # noqa: BLE001 — isolate per-feed failures
                # One provider's feed must never abort the whole tick or skip
                # the remaining feeds. Log with traceback (Sentry-visible) and
                # record the error, then carry on with the next feed.
                log.exception("Unexpected error syncing feed %s; skipping", feed.dbid)
                try:
                    feed.last_error = f"unexpected error: {exc.__class__.__name__}"
                    feed.save()
                except Exception:
                    log.exception("Failed to record last_error for feed %s", feed.dbid)
        return effects

    def _lookahead_days(self) -> int:
        try:
            return int(self.secrets.get("LOOKAHEAD_DAYS", str(LOOKAHEAD_DAYS_DEFAULT)))
        except (TypeError, ValueError):
            log.warning("LOOKAHEAD_DAYS not parseable; using default %d", LOOKAHEAD_DAYS_DEFAULT)
            return LOOKAHEAD_DAYS_DEFAULT

    def _max_deletes_per_sync(self) -> int:
        try:
            return int(
                self.secrets.get("MAX_DELETES_PER_SYNC", str(MAX_DELETES_PER_SYNC_DEFAULT))
            )
        except (TypeError, ValueError):
            log.warning(
                "MAX_DELETES_PER_SYNC not parseable; using default %d",
                MAX_DELETES_PER_SYNC_DEFAULT,
            )
            return MAX_DELETES_PER_SYNC_DEFAULT

    def _sync_feed(
        self,
        feed: StaffCalendarFeed,
        now: datetime,
        lookahead_days: int,
        max_deletes: int,
    ) -> list[Effect]:
        calendar_id, cal_effects = get_admin_calendar_id(feed.staff_id)
        if not calendar_id:
            log.warning(
                "Skipping feed %s: could not resolve or provision Admin calendar for staff %s",
                feed.dbid,
                feed.staff_id,
            )
            feed.last_error = "unable to provision Admin calendar for this provider"
            feed.save()
            return []

        result = fetch_feed(feed.ics_url, etag=feed.last_etag, last_modified=feed.last_modified)
        log.info(
            "Synced feed %s url=%s result=%s",
            feed.dbid,
            redact_url(feed.ics_url),
            result.__class__.__name__,
        )

        if isinstance(result, NotModified):
            feed.last_sync_at = now
            feed.last_error = None
            feed.save()
            return cal_effects
        if isinstance(result, (Unauthorized, NotFound)):
            feed.is_active = False
            feed.last_error = result.__class__.__name__
            feed.save()
            return []
        if isinstance(result, TransientError):
            feed.last_error = result.reason
            feed.save()
            return []

        assert isinstance(result, FetchOk)

        try:
            parsed = parse_ics(result.body, now=now, lookahead_days=lookahead_days)
        except IcsParseError as exc:
            log.warning("Parse failure feed=%s err=%s", feed.dbid, exc)
            feed.last_error = f"parse failure: {exc.__class__.__name__}"
            feed.save()
            return []

        # The live calendar is the source of truth for what exists; the feed is
        # the source of truth for what should. Read live blocks (by their real
        # uuids) within the same window the parser covers so the two sets line up.
        window_end = now + timedelta(days=lookahead_days)
        live_by_time = busy_ids_by_time(calendar_id, now, window_end)

        # Safety guard: a feed that parses to zero events while the calendar still
        # holds blocks is almost always a transient upstream glitch, not the
        # provider clearing their calendar. Skip deletions rather than wipe every
        # block; a genuinely emptied feed clears on a later tick once confirmed.
        if not parsed and live_by_time:
            feed.last_error = "feed parsed but empty; deletions skipped"
            feed.save()
            return cal_effects

        effects = self._reconcile(calendar_id, parsed, live_by_time, max_deletes)

        feed.last_sync_at = now
        feed.last_etag = result.etag
        feed.last_modified = result.last_modified
        feed.last_error = None
        feed.save()
        return [*cal_effects, *effects]

    def _reconcile(
        self,
        calendar_id: str,
        parsed: list[ParsedEvent],
        live_by_time: dict[tuple[datetime, datetime], list[str]],
        max_deletes: int,
    ) -> list[Effect]:
        """Reconcile the live Admin calendar to the parsed feed by time window.

        Every block is matched on its ``(starts_at, ends_at)`` pair, never on the
        stored id. A live block the feed no longer wants is deleted by its *real*
        uuid; a block the feed wants that isn't live yet is created. Because it
        reconciles against the live calendar rather than a tracking table, it both
        stops accruing orphans and cleans up ones already stranded by KOALA-6372.
        """
        desired: Counter[tuple[datetime, datetime]] = Counter(
            (ev.starts_at, ev.ends_at) for ev in parsed
        )
        effects: list[Effect] = []

        # Delete surplus: any block present more times than the feed wants at that
        # time. A feed count of zero deletes them all — that is the orphan
        # cleanup. Bounded by max_deletes so a partial parse can't mass-delete;
        # the remainder clears on subsequent ticks.
        deletes = 0
        hit_cap = False
        for key, real_ids in live_by_time.items():
            keep = desired.get(key, 0)
            for real_id in real_ids[keep:]:
                if deletes >= max_deletes:
                    hit_cap = True
                    break
                effects.append(Event(event_id=real_id).delete())
                deletes += 1
            if hit_cap:
                break
        if hit_cap:
            log.warning(
                "external_calendar_busy_blocks: hit delete cap of %d on calendar %s; "
                "remaining orphaned blocks will clear on subsequent ticks",
                max_deletes,
                calendar_id,
            )

        # Create shortfall: the feed wants more blocks at this time than are live.
        for (starts_at, ends_at), want in desired.items():
            have = len(live_by_time.get((starts_at, ends_at), ()))
            for _ in range(want - have):
                # event_id is intentionally omitted: the create interpreter
                # ignores any supplied id and assigns its own (KOALA-6372). The
                # real id is read back from the calendar on later ticks.
                effects.append(
                    Event(
                        calendar_id=calendar_id,
                        title="Busy",
                        starts_at=starts_at,
                        ends_at=ends_at,
                    ).create()
                )

        return effects
