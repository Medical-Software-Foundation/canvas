"""Date parsing for Oura API values.

Oura reports each summary against a ``day`` that is already the ring owner's
local calendar date, so no timezone conversion is applied to it.
"""

import datetime as dt
from typing import Any
from zoneinfo import ZoneInfo


def local_today(now: dt.datetime, environment: Any) -> dt.date:
    """Today's date at the practice, from the instance's installation time zone.

    Oura files data under the wearer's local date, and a plugin has no time
    zone for the wearer. The practice's zone is the closest source available,
    and far closer than UTC, which runs a day ahead every US evening.
    """
    name = (environment or {}).get("INSTALLATION_TIME_ZONE") or "UTC"
    return now.astimezone(ZoneInfo(name)).date()


def parse_day(value: Any) -> dt.date | None:
    """Parse an Oura ``day`` value (``YYYY-MM-DD``) into a date, else None."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return dt.date.fromisoformat(value.strip())
    except ValueError:
        return None
