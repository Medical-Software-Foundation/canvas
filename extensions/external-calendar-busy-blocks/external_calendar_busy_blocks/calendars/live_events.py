"""Read a provider's live "Busy" Admin-calendar events by their real UUIDs.

The cron writes each block with ``Event(...).create()``, but Canvas's
calendar-event create interpreter discards the supplied ``event_id`` and assigns
a fresh uuid (KOALA-6372). The id the plugin stored therefore never matches the
live event, so update/delete by that id fail: update raises "Event does not
exist" and delete silently no-ops. That is why orphaned blocks accumulate and
can never be cleaned up.

The fix is to stop trusting the stored id. Read each block's *real* uuid back
from the calendar data model and reconcile on the live calendar, matching blocks
by their ``(starts_at, ends_at)`` window. Nothing here depends on the phantom id.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from canvas_sdk.v1.data.calendar import Event as CalendarEvent

BUSY_TITLE = "Busy"


def live_busy_events(
    calendar_id: str, now: datetime, window_end: datetime | None = None
):
    """Future, non-cancelled "Busy" events on one Admin calendar.

    Mirrors the ICS parser's window so a reconcile compares like for like: an
    event counts as live when it has not ended (``ends_at > now``) and, when
    ``window_end`` is given, starts before the look-ahead horizon
    (``starts_at < window_end``). Omit ``window_end`` to select every not-yet-
    ended block, which disconnect uses to remove all of a provider's blocks.
    """
    qs = CalendarEvent.objects.filter(
        calendar__id=calendar_id,
        title=BUSY_TITLE,
        is_cancelled=False,
        ends_at__gt=now,
    )
    if window_end is not None:
        qs = qs.filter(starts_at__lt=window_end)
    return qs


def busy_ids_by_time(
    calendar_id: str, now: datetime, window_end: datetime
) -> dict[tuple[datetime, datetime], list[str]]:
    """Map each live block's ``(starts_at, ends_at)`` to the real uuids there.

    A slot can hold more than one uuid when duplicate blocks exist (e.g. a
    triplicated import). The reconcile uses each list's length to decide how many
    blocks to keep versus delete at that time.
    """
    by_time: dict[tuple[datetime, datetime], list[str]] = defaultdict(list)
    for event in live_busy_events(calendar_id, now, window_end):
        by_time[(event.starts_at, event.ends_at)].append(str(event.id))
    return by_time


def live_busy_counts(calendar_ids: list[str], now: datetime) -> dict[str, int]:
    """Count future, non-cancelled "Busy" events per calendar in one query.

    Returns ``{calendar_uuid_str: count}`` so the admin config page can show each
    provider's real block count without an N+1 over calendars.
    """
    counts: dict[str, int] = {}
    if not calendar_ids:
        return counts
    rows = CalendarEvent.objects.filter(
        calendar__id__in=calendar_ids,
        title=BUSY_TITLE,
        is_cancelled=False,
        ends_at__gt=now,
    ).values_list("calendar__id", flat=True)
    for cal_id in rows:
        key = str(cal_id)
        counts[key] = counts.get(key, 0) + 1
    return counts
