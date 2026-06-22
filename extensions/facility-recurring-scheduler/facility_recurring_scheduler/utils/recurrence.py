"""Shared recurrence date calculation utilities."""

import datetime
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta

from facility_recurring_scheduler.utils.constants import RecurrenceEnum


def calculate_recurrence_date(
    start_time: datetime.datetime,
    count: int,
    recurrence: str,
    local_tz: ZoneInfo,
) -> datetime.datetime:
    """Calculate a recurring event date preserving wall-clock time across DST changes.

    Monthly recurrence is by ordinal weekday rather than calendar date: an event
    on the 3rd Tuesday recurs on the 3rd Tuesday of each following month, so the
    day of week never wanders onto a weekend and there is no month-length drift.
    An anchor that is the 5th occurrence of its weekday (a day-of-week that does
    not occur 5 times in every month) recurs on the *last* such weekday instead.

    Args:
        start_time: The base datetime to offset from (UTC or tz-aware). For
            monthly recurrence this must be the series' original anchor, since
            the ordinal weekday is derived from it.
        count: Number of recurrence intervals to advance.
        recurrence: Recurrence pattern string (e.g. "daily", "weekly", "monthly").
        local_tz: The local timezone for wall-clock preservation.

    Returns:
        A UTC datetime for the new occurrence.

    Raises:
        ValueError: If recurrence is not a recognized pattern.
    """
    utc_tz = ZoneInfo("UTC")

    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=utc_tz)
    local_time = start_time.astimezone(local_tz)

    if recurrence == RecurrenceEnum.DAILY.value:
        new_local_time = local_time + relativedelta(days=count)
    elif recurrence == RecurrenceEnum.WEEKLY.value:
        new_local_time = local_time + relativedelta(weeks=count)
    elif recurrence == RecurrenceEnum.EVERY_2_WEEKS.value:
        new_local_time = local_time + relativedelta(weeks=2 * count)
    elif recurrence == RecurrenceEnum.EVERY_3_WEEKS.value:
        new_local_time = local_time + relativedelta(weeks=3 * count)
    elif recurrence == RecurrenceEnum.MONTHLY.value:
        # Ordinal weekday of the anchor, e.g. "3rd Tuesday" (Monday=0 .. Sunday=6).
        weekday_target = local_time.weekday()
        ordinal = (local_time.day - 1) // 7 + 1

        # Jump to the target month, anchored on day 1, preserving wall-clock time.
        # (The Canvas sandbox only allows `relativedelta` from dateutil — not the
        # MO/TU/... weekday tokens — so the ordinal-weekday date is computed here.)
        target = (local_time + relativedelta(months=count)).replace(day=1)
        # Day-of-month of the first occurrence of the target weekday.
        first_occurrence_day = 1 + (weekday_target - target.weekday()) % 7
        # Last day of the target month (day=31 clamps to the real month length).
        last_day = (target + relativedelta(day=31)).day

        if ordinal >= 5:
            # The 5th weekday doesn't exist every month — fall back to the last one.
            day = first_occurrence_day + ((last_day - first_occurrence_day) // 7) * 7
        else:
            day = first_occurrence_day + (ordinal - 1) * 7

        new_local_time = target.replace(day=day)
    else:
        raise ValueError(f"Unknown recurrence type: {recurrence!r}")

    result: datetime.datetime = new_local_time.astimezone(utc_tz)
    return result
