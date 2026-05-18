"""Cadence-aware advancement of the membership billing date.

Plans declare a ``cadence`` of ``daily``, ``weekly``, ``monthly``, ``quarterly``,
or ``annually``. ``advance_billing_date`` advances *current* by one such cycle,
clamping to the last day of the target month when the source day overflows
(Jan 31 → Feb 28; Aug 31 → Nov 30; Feb 29 → next year's Feb 28).

An unknown cadence falls back to monthly so a misconfigured plan keeps billing
on a sane cycle while the warning lands in the cron logs.
"""
from datetime import date, timedelta

from logger import log

DAILY = "daily"
WEEKLY = "weekly"
MONTHLY = "monthly"
QUARTERLY = "quarterly"
ANNUALLY = "annually"

VALID_CADENCES = (DAILY, WEEKLY, MONTHLY, QUARTERLY, ANNUALLY)
DEFAULT_CADENCE = MONTHLY

# Short suffixes appended to per-cycle prices ("$49.00/mo", "$1.00/day", …).
_CADENCE_SUFFIX = {
    DAILY: "/day",
    WEEKLY: "/wk",
    MONTHLY: "/mo",
    QUARTERLY: "/qtr",
    ANNUALLY: "/yr",
}


def cadence_suffix(cadence: str | None) -> str:
    """Return the short price suffix for *cadence* (defaults to ``/mo``)."""
    return _CADENCE_SUFFIX.get(cadence or DEFAULT_CADENCE, _CADENCE_SUFFIX[DEFAULT_CADENCE])


def advance_billing_date(current: date, cadence: str | None) -> date:
    """Return the next billing date for *current* given *cadence*."""
    chosen = cadence if cadence in VALID_CADENCES else DEFAULT_CADENCE
    if chosen != cadence:
        log.warning(
            f"portal_membership: unknown cadence {cadence!r}, falling back to {DEFAULT_CADENCE}"
        )
    if chosen == DAILY:
        return current + timedelta(days=1)
    if chosen == WEEKLY:
        return current + timedelta(days=7)
    if chosen == MONTHLY:
        return _add_months(current, 1)
    if chosen == QUARTERLY:
        return _add_months(current, 3)
    return _add_months(current, 12)


def next_billing_iso(current: date | str, cadence: str | None) -> str:
    """ISO-8601 string form of :func:`advance_billing_date`."""
    base = current if isinstance(current, date) else date.fromisoformat(str(current))
    return advance_billing_date(base, cadence).isoformat()


def _add_months(current: date, months: int) -> date:
    month_index = current.month - 1 + months
    year = current.year + month_index // 12
    month = (month_index % 12) + 1
    day = current.day
    while day > 0:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1
    return date(year, month, 1)
