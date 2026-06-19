"""Pure metric computation over an instrument's sorted point list.

Data only: latest score, signed numeric change vs the prior assessment,
days since the last assessment, and total count. No interpretation.
"""

from __future__ import annotations

from datetime import date

import arrow


def compute_metrics(points: list[dict], as_of: date) -> dict:
    """Compute the four data-only metrics for a sorted point list.

    Returns keys: latest, change, days_since, total.
    `points` must be sorted ascending by date (build_series guarantees this).
    """
    if not points:
        return {"latest": None, "change": None, "days_since": None, "total": 0}

    latest = points[-1]["value"]
    change = None
    if len(points) >= 2:
        change = latest - points[-2]["value"]

    last_date = arrow.get(points[-1]["date"]).date()
    days_since = (as_of - last_date).days

    return {
        "latest": latest,
        "change": change,
        "days_since": days_since,
        "total": len(points),
    }
