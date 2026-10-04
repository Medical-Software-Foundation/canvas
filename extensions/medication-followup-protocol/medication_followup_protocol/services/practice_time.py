"""The practice timezone, and the one place a UTC stamp becomes a local date.

The scheduler stamps its event in UTC and every date this plugin stores is a date in the
practice timezone, so exactly one conversion exists and it lives here.

The SDK carries no practice timezone. PracticeLocation, Organization and
PracticeLocationSetting were all read and none of them holds one, and the only timezone
fields on the platform are per calendar and per user rather than per practice. The
specification records the timezone choice as ours for that reason, so this constant is the
seam. A practice on another timezone changes this one line.
"""

from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo

#: The timezone every stored date is expressed in.
PRACTICE_TIMEZONE = ZoneInfo("UTC")


def to_practice_date(moment: datetime.datetime) -> datetime.date:
    """Take the date a moment falls on in the practice timezone.

    A naive datetime is read as UTC, since UTC is what the scheduler sends.
    """
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)
    return moment.astimezone(PRACTICE_TIMEZONE).date()


def today() -> datetime.date:
    """Today's date in the practice timezone."""
    return to_practice_date(datetime.datetime.now(datetime.timezone.utc))
