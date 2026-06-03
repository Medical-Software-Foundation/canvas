from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from external_calendar_busy_blocks.ics.types import IcsParseError


@dataclass(frozen=True)
class DateValue:
    """A parsed ICS date or datetime value.

    `moment` is the absolute instant in UTC (used for ordering, windowing, and
    persistence). `local` is the same instant expressed in the value's own
    evaluation timezone (the TZID, the calendar default for floating times, or
    UTC for Zulu/all-day values). RRULE expansion must evaluate BYDAY /
    BYMONTHDAY in `local` so occurrences land on the correct local calendar day
    (RFC 5545 §3.3.10); converting to UTC first would shift the day for any
    event whose wall-clock time crosses midnight UTC.
    """

    moment: datetime
    is_all_day: bool
    local: datetime


def parse_ics_datetime(
    value: str,
    params: dict[str, str],
    default_tz: str,
) -> DateValue:
    """Parse an ICS DTSTART/DTEND/EXDATE/etc. value to a UTC datetime.

    Args:
        value: the property value, e.g. "20260601T090000", "20260601T140000Z",
               or "20260601".
        params: the property parameters dict. Honors VALUE=DATE and TZID.
        default_tz: fallback IANA timezone for floating times (no TZID, no Z).
                    Typically the calendar's X-WR-TIMEZONE or "UTC".
    """
    if params.get("VALUE", "").upper() == "DATE":
        if len(value) != 8 or not value.isdigit():
            raise IcsParseError(f"malformed DATE value: {value!r}")
        try:
            midnight = datetime(
                int(value[0:4]),
                int(value[4:6]),
                int(value[6:8]),
                tzinfo=timezone.utc,
            )
            # All-day values are date-only and timezone-agnostic; local == UTC.
            return DateValue(moment=midnight, is_all_day=True, local=midnight)
        except ValueError as exc:
            raise IcsParseError(f"invalid DATE: {value!r}") from exc

    is_utc = value.endswith("Z")
    body = value[:-1] if is_utc else value

    if len(body) != 15 or body[8] != "T":
        raise IcsParseError(f"malformed DATE-TIME value: {value!r}")

    try:
        naive = datetime(
            int(body[0:4]),
            int(body[4:6]),
            int(body[6:8]),
            int(body[9:11]),
            int(body[11:13]),
            int(body[13:15]),
        )
    except ValueError as exc:
        raise IcsParseError(f"invalid DATE-TIME: {value!r}") from exc

    if is_utc:
        utc_aware = naive.replace(tzinfo=timezone.utc)
        # Event is defined in UTC; local evaluation zone is UTC.
        return DateValue(moment=utc_aware, is_all_day=False, local=utc_aware)

    tzid = params.get("TZID", default_tz)
    try:
        zone = ZoneInfo(tzid)
    except KeyError as exc:
        raise IcsParseError(f"unknown TZID: {tzid!r}") from exc

    local_aware = naive.replace(tzinfo=zone)
    return DateValue(
        moment=local_aware.astimezone(timezone.utc),
        is_all_day=False,
        local=local_aware,
    )
