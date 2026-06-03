from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from external_calendar_busy_blocks.ics.types import IcsParseError


@dataclass(frozen=True)
class DateValue:
    """A parsed ICS date or datetime value, always tz-aware UTC."""

    moment: datetime
    is_all_day: bool


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
            return DateValue(
                moment=datetime(
                    int(value[0:4]),
                    int(value[4:6]),
                    int(value[6:8]),
                    tzinfo=timezone.utc,
                ),
                is_all_day=True,
            )
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
        return DateValue(moment=naive.replace(tzinfo=timezone.utc), is_all_day=False)

    tzid = params.get("TZID", default_tz)
    try:
        zone = ZoneInfo(tzid)
    except KeyError as exc:
        raise IcsParseError(f"unknown TZID: {tzid!r}") from exc

    return DateValue(
        moment=naive.replace(tzinfo=zone).astimezone(timezone.utc),
        is_all_day=False,
    )
