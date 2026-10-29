"""The logged-in clinician's own availability, for shading the schedule grid.

Canvas links availability calendars to staff by title: "<First Last>: Clinic"
(open for booking) and "<First Last>: Admin" (blocked), optionally followed by
": <location>". Only calendars carrying the clinician's own name are read, so
no other provider's availability can reach the page.
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from canvas_sdk.v1.data.calendar import Calendar, Event
from canvas_sdk.v1.data.staff import Staff
from django.db.models import Q

_DAY_MAP = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
_KIND_BY_TYPE = {"clinic": "available", "admin": "busy"}


def _parse_rrule(rrule: str) -> dict[str, str]:
    parts = (part.split("=", 1) for part in rrule.replace("RRULE:", "").split(";"))
    return {
        pair[0].strip().upper(): pair[1].strip() for pair in parts if len(pair) == 2
    }


def _until(rule: dict[str, str]) -> date | None:
    raw = rule.get("UNTIL", "")
    try:
        return datetime.strptime(raw[:8], "%Y%m%d").date() if raw else None
    except ValueError:
        return None


def occurs_on(event: Event, day: date, tz: ZoneInfo) -> bool:
    """True when a (possibly repeating) event has an occurrence on `day` (calendar-local)."""
    first = event.starts_at.astimezone(tz).date()
    if not event.recurrence:
        return first == day
    if day < first:
        return False
    if (
        event.recurrence_ends_at
        and day > event.recurrence_ends_at.astimezone(tz).date()
    ):
        return False
    rule = _parse_rrule(event.recurrence)
    until = _until(rule)
    if until and day > until:
        return False
    try:
        interval = max(int(rule.get("INTERVAL", "1")), 1)
    except ValueError:
        interval = 1
    freq = rule.get("FREQ", "")
    if freq == "DAILY":
        return (day - first).days % interval == 0
    if freq == "WEEKLY":
        days = {_DAY_MAP[d] for d in rule.get("BYDAY", "").split(",") if d in _DAY_MAP}
        if day.weekday() not in (days or {first.weekday()}):
            return False
        # RRULE weeks start on Monday; count whole weeks between the two Mondays.
        weeks = (
            (day - timedelta(days=day.weekday()))
            - (first - timedelta(days=first.weekday()))
        ).days // 7
        return weeks % interval == 0
    return False


def window_on(
    event: Event, day: date, tz: ZoneInfo
) -> tuple[datetime, datetime] | None:
    """The occurrence that starts on `day` (calendar-local), keeping its full length.

    An overnight block runs into the next day; the page clips each day's column itself.
    """
    if event.is_all_day:
        start = datetime.combine(day, time.min, tzinfo=tz)
        return start, start + timedelta(days=1)
    start = datetime.combine(day, event.starts_at.astimezone(tz).time(), tzinfo=tz)
    end = start + (event.ends_at - event.starts_at)
    return (start, end) if end > start else None


def _calendar_kind(title: str, name: str) -> str | None:
    rest = title[len(name) + 1 :].strip()
    calendar_type = rest.split(":", 1)[0].strip().lower()
    return _KIND_BY_TYPE.get(calendar_type)


def own_blocks(staff: Staff, start: datetime, end: datetime) -> list[dict]:
    """Available and blocked time for `staff` between start and end (aware datetimes)."""
    name = f"{staff.first_name} {staff.last_name}".strip()
    if not name:
        return []
    calendars = {
        cal.dbid: (cal, kind)
        for cal in Calendar.objects.filter(
            Q(title__startswith=f"{name}: Clinic")
            | Q(title__startswith=f"{name}: Admin")
        )
        if (kind := _calendar_kind(cal.title, name))
    }
    if not calendars:
        return []

    events = list(
        Event.objects.filter(
            calendar_id__in=calendars, is_cancelled=False, starts_at__lt=end
        )
        .filter(Q(recurrence__isnull=False) & ~Q(recurrence="") | Q(ends_at__gt=start))
        .select_related("calendar")
    )
    # A changed or deleted occurrence of a repeating event is stored as its own
    # event pointing at the parent; skip the parent's occurrence on that day.
    overridden: dict[int, list[datetime]] = {}
    for child in Event.objects.filter(
        recurring_parent_event_id__in=[e.dbid for e in events if e.recurrence],
        original_starts_at__isnull=False,
    ):
        overridden.setdefault(child.recurring_parent_event_id, []).append(
            child.original_starts_at
        )

    blocks = []
    for ev in events:
        cal, kind = calendars[ev.calendar_id]
        tz = ZoneInfo(str(cal.timezone or "UTC"))
        day = start.astimezone(tz).date() - timedelta(days=1)
        last = end.astimezone(tz).date()
        moved = {dt.astimezone(tz).date() for dt in overridden.get(ev.dbid, [])}
        while day <= last:
            if occurs_on(ev, day, tz) and day not in moved:
                window = window_on(ev, day, tz)
                if window and window[1] > start and window[0] < end:
                    blocks.append(
                        {
                            "kind": kind,
                            "title": ev.title or "",
                            "start": window[0].isoformat(),
                            "end": window[1].isoformat(),
                        }
                    )
            day += timedelta(days=1)
    blocks.sort(key=lambda b: b["start"])
    return blocks
