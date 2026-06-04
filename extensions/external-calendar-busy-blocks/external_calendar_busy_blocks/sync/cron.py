import uuid
from datetime import datetime, timezone
from typing import Any

from logger import log

from canvas_sdk.effects import Effect
from canvas_sdk.effects.calendar import Event
from canvas_sdk.handlers.cron_task import CronTask
from canvas_sdk.v1.data.staff import Staff

from external_calendar_busy_blocks.calendars.admin_lookup import find_admin_calendar_id
from external_calendar_busy_blocks.data.models import (
    ImportedEvent,
    StaffCalendarFeed,
)
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


class SyncCron(CronTask):
    """Polls every 15 minutes and reconciles ICS feeds to Canvas Admin events."""

    SCHEDULE = "*/15 * * * *"

    def execute(self) -> list[Effect]:
        now = datetime.now(timezone.utc)
        lookahead = self._lookahead_days()
        effects: list[Effect] = []

        for feed in StaffCalendarFeed.objects.filter(is_active=True):
            try:
                effects.extend(self._sync_feed(feed, now, lookahead))
            except Exception as exc:  # noqa: BLE001 — isolate per-feed failures
                # One provider's feed must never abort the whole tick or skip
                # the remaining feeds. Log with traceback (Sentry-visible) and
                # record the error, then carry on with the next feed.
                log.exception("Unexpected error syncing feed %s; skipping", feed.dbid)
                try:
                    feed.last_error = f"unexpected error: {type(exc).__name__}"
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

    def _sync_feed(
        self,
        feed: StaffCalendarFeed,
        now: datetime,
        lookahead_days: int,
    ) -> list[Effect]:
        try:
            staff = Staff.objects.get(id=feed.staff_id)
        except Staff.DoesNotExist:
            log.warning("Skipping feed %s: staff %s not found", feed.dbid, feed.staff_id)
            feed.last_error = f"staff {feed.staff_id} not found"
            feed.save()
            return []

        calendar_id = find_admin_calendar_id(staff)
        if calendar_id is None:
            feed.last_error = "no Admin calendar for this provider"
            feed.save()
            return []

        result = fetch_feed(feed.ics_url, etag=feed.last_etag, last_modified=feed.last_modified)
        log.info(
            "Synced feed %s url=%s result=%s",
            feed.dbid,
            redact_url(feed.ics_url),
            type(result).__name__,
        )

        if isinstance(result, NotModified):
            feed.last_sync_at = now
            feed.last_error = None
            feed.save()
            return []
        if isinstance(result, (Unauthorized, NotFound)):
            feed.is_active = False
            feed.last_error = type(result).__name__
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
            feed.last_error = f"parse failure: {type(exc).__name__}"
            feed.save()
            return []

        # Only reconcile events that haven't ended yet. The parser never yields
        # past occurrences, so including past ImportedEvent rows here would make
        # the diff treat them as "removed from the feed" and delete them within
        # ~15 min of the meeting ending. Per the spec, past events age out
        # naturally on the source calendar rather than being deleted by the cron.
        existing = list(
            ImportedEvent.objects.filter(staff_id=feed.staff_id, ends_at__gte=now)
        )

        if not parsed and existing:
            feed.last_error = "feed parsed but empty; deletions skipped"
            feed.save()
            return []

        effects = self._diff_and_emit(feed, calendar_id, parsed, existing, now)

        feed.last_sync_at = now
        feed.last_etag = result.etag
        feed.last_modified = result.last_modified
        feed.last_error = None
        feed.save()
        return effects

    def _diff_and_emit(
        self,
        feed: StaffCalendarFeed,
        calendar_id: str,
        parsed: list[ParsedEvent],
        existing: list[Any],
        now: datetime,
    ) -> list[Effect]:
        by_key_existing = {(e.ics_uid, e.recurrence_id): e for e in existing}
        seen_keys: set[tuple[str, str | None]] = set()
        effects: list[Effect] = []

        for ev in parsed:
            key = (ev.uid, ev.recurrence_id)
            seen_keys.add(key)
            prior = by_key_existing.get(key)

            if prior is None:
                new_event_id = str(uuid.uuid4())
                effects.append(
                    Event(
                        event_id=new_event_id,
                        calendar_id=calendar_id,
                        title="Busy",
                        starts_at=ev.starts_at,
                        ends_at=ev.ends_at,
                    ).create()
                )
                ImportedEvent(
                    staff_id=feed.staff_id,
                    ics_uid=ev.uid,
                    recurrence_id=ev.recurrence_id,
                    canvas_event_id=new_event_id,
                    sequence=ev.sequence,
                    starts_at=ev.starts_at,
                    ends_at=ev.ends_at,
                    is_all_day=ev.is_all_day,
                    last_seen=now,
                ).save()
                continue

            if (
                prior.starts_at == ev.starts_at
                and prior.ends_at == ev.ends_at
                and prior.sequence == ev.sequence
            ):
                prior.last_seen = now
                prior.save()
                continue

            effects.append(
                Event(
                    event_id=prior.canvas_event_id,
                    title="Busy",
                    starts_at=ev.starts_at,
                    ends_at=ev.ends_at,
                ).update()
            )
            prior.starts_at = ev.starts_at
            prior.ends_at = ev.ends_at
            prior.sequence = ev.sequence
            prior.last_seen = now
            prior.save()

        for key, row in by_key_existing.items():
            if key in seen_keys:
                continue
            effects.append(Event(event_id=row.canvas_event_id).delete())
            row.delete()

        return effects
