"""Wait-time and fill figures for the nightly job.

Pure arithmetic over already-fetched rows, so the numbers can be checked
without a database.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from scheduling_waitlist.constants import (
    STATUS_EXPIRED,
    STATUS_OFFERED,
    STATUS_REMOVED,
    STATUS_SCHEDULED,
    STATUS_WAITING,
)
from scheduling_waitlist.services.serializers import days_waiting

REPORTED_STATUSES = (
    STATUS_WAITING,
    STATUS_OFFERED,
    STATUS_SCHEDULED,
    STATUS_REMOVED,
    STATUS_EXPIRED,
)


def median(values: list[int]) -> float:
    """Middle value, averaging the two middle values for an even count."""
    if not values:
        return 0.0
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[midpoint])
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2


def summarize(entries: list[Any], *, today: date) -> dict[str, Any]:
    """How long people are waiting, and how often the list ends in a booking.

    ``fill_rate`` counts entries that reached a booking as a share of those
    that reached any conclusion. Entries still waiting are excluded from the
    denominator: counting them as failures would make a healthy list with a
    long tail look broken.
    """
    counts = {status: 0 for status in REPORTED_STATUSES}
    waits: list[int] = []

    for entry in entries:
        status = getattr(entry, "status", "") or ""
        if status in counts:
            # Explicit reassignment rather than ``counts[status] += 1``: the
            # RestrictedPython sandbox rejects augmented assignment to a dict
            # item, so the shorter form fails on the instance only.
            counts[status] = counts[status] + 1
        if status in (STATUS_WAITING, STATUS_OFFERED):
            waits.append(days_waiting(getattr(entry, "created_at", None), today))

    concluded = counts[STATUS_SCHEDULED] + counts[STATUS_REMOVED] + counts[STATUS_EXPIRED]
    fill_rate = (counts[STATUS_SCHEDULED] / concluded) if concluded else 0.0

    return {
        "counts": counts,
        "open_entries": counts[STATUS_WAITING] + counts[STATUS_OFFERED],
        "average_wait_days": round(sum(waits) / len(waits), 1) if waits else 0.0,
        "median_wait_days": median(waits),
        "longest_wait_days": max(waits) if waits else 0,
        "fill_rate": round(fill_rate, 3),
    }


def format_summary(summary: dict[str, Any]) -> str:
    """One log line an operator can read without unpacking a dictionary."""
    counts = summary["counts"]
    return (
        "scheduling_waitlist metrics: "
        f"{summary['open_entries']} open "
        f"(waiting {counts[STATUS_WAITING]}, offered {counts[STATUS_OFFERED]}), "
        f"average wait {summary['average_wait_days']}d, "
        f"median {summary['median_wait_days']}d, "
        f"longest {summary['longest_wait_days']}d, "
        f"fill rate {summary['fill_rate']:.0%} "
        f"(scheduled {counts[STATUS_SCHEDULED]}, "
        f"removed {counts[STATUS_REMOVED]}, expired {counts[STATUS_EXPIRED]})"
    )
