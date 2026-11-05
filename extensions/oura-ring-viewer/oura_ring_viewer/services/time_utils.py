"""Date parsing for Oura API values.

Oura reports each summary against a ``day`` that is already the ring owner's
local calendar date, so no timezone conversion is applied to it.
"""

import datetime as dt
from typing import Any


def parse_day(value: Any) -> dt.date | None:
    """Parse an Oura ``day`` value (``YYYY-MM-DD``) into a date, else None."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return dt.date.fromisoformat(value.strip())
    except ValueError:
        return None
