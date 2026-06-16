"""Recurrence rule encoding + occurrence-date expansion for the scheduling app.

The override modal can't use the built-in form-field/metadata path the
``recurring_appointments`` example uses, so the booking flow stamps the rule onto
the *parent* appointment as a plugin-namespaced external identifier (see
booking.py) and the APPOINTMENT_CREATED handler (handlers/recurrence.py) reads it
back to create the child appointments. This module is the shared, pure core: the
identifier system, the rule (de)serialization, and the date expansion.
"""

from __future__ import annotations

import datetime
import json
from typing import Any

from dateutil.relativedelta import relativedelta

# Namespaced identifier system carrying the recurrence rule from /book to the
# APPOINTMENT_CREATED handler. Children are created WITHOUT it, so the handler
# skips them — that's what prevents infinite recursion.
RECURRENCE_SYSTEM = "scheduling_app:recurrence"

# Safety bound on how many child appointments a single series can spawn.
MAX_OCCURRENCES = 60

FREQUENCIES = ("daily", "weekly", "monthly")


def encode_recurrence(recurrence: dict[str, Any]) -> str:
    """Serialize a recurrence rule for the external-identifier value."""
    return json.dumps(recurrence, separators=(",", ":"))


def decode_recurrence(value: str) -> dict[str, Any] | None:
    """Parse a stored recurrence rule, or None if it's invalid/has no end condition."""
    try:
        rule = json.loads(value)
    except (TypeError, ValueError):
        return None
    if not isinstance(rule, dict) or rule.get("frequency") not in FREQUENCIES:
        return None
    # Require an end condition so a malformed rule can't spin up to the cap.
    if rule.get("count") is None and not rule.get("until"):
        return None
    return rule


def _shift(start: datetime.datetime, frequency: str, units: int) -> datetime.datetime:
    if frequency == "daily":
        return start + datetime.timedelta(days=units)
    if frequency == "weekly":
        return start + datetime.timedelta(weeks=units)
    return start + relativedelta(months=units)  # monthly


def _until_cutoff(until: str, start: datetime.datetime) -> datetime.datetime | None:
    """Inclusive end-of-day cutoff for an 'until' date, in the start's tz frame."""
    try:
        day = datetime.date.fromisoformat(until)
    except (TypeError, ValueError):
        return None
    return datetime.datetime.combine(day, datetime.time.max, tzinfo=start.tzinfo)


def occurrence_start_times(
    start: datetime.datetime,
    recurrence: dict[str, Any],
    max_occurrences: int = MAX_OCCURRENCES,
) -> list[datetime.datetime]:
    """Child start times for a series whose first (parent) occurrence is at ``start``.

    ``recurrence`` is ``{frequency, interval, count?|until?}`` where ``count`` is
    the TOTAL occurrences including the parent (so children = count - 1) and
    ``until`` is an inclusive end date. Capped at ``max_occurrences`` children.
    """
    frequency = recurrence.get("frequency")
    if frequency not in FREQUENCIES:
        return []
    interval = max(int(recurrence.get("interval") or 1), 1)

    count = recurrence.get("count")
    children_from_count = max(int(count) - 1, 0) if count else None
    cutoff = _until_cutoff(recurrence["until"], start) if recurrence.get("until") else None

    starts: list[datetime.datetime] = []
    occurrence = 1
    while len(starts) < max_occurrences:
        if children_from_count is not None and len(starts) >= children_from_count:
            break
        nxt = _shift(start, frequency, occurrence * interval)
        if cutoff is not None and nxt > cutoff:
            break
        starts.append(nxt)
        occurrence += 1
    return starts
