"""Overview tab data builder — real-data queries against Claim + Appointment.

Collected amounts are computed via DB aggregate through the Claim→Posting→
NewLineItemPayment reverse-relation path. This avoids the O(N × postings)
Python iteration that `Claim.total_paid` would incur, without needing to
import Posting (blocked in the plugin sandbox).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal, TypedDict

import arrow
from canvas_sdk.v1.data.appointment import Appointment
from canvas_sdk.v1.data.claim import Claim
from django.db.models import Count, Q, Sum

from billing_dashboard.data.claim_queue import ClaimQueueState
from billing_dashboard.data.insights import compute_insights
from billing_dashboard.data.mock import financial_overview as mock_overview
from billing_dashboard.data.windows import (
    last_month_range,
    next_month_range,
    this_month_range,
    trailing_12_months_range,
    trailing_30_days_range,
    trailing_90_days_range,
)


class SummaryEntry(TypedDict):
    """Envelope used for every summary metric returned by this module.

    ``source`` lets the UI badge mock values; downstream consumers (insights
    rules, JS metric cards) read ``value`` and decide based on ``source``.

    - ``"real"``: value was computed from a real DB query
    - ``"mock"``: value came from the mock fallback (badge as Demo data)
    - ``"no_baseline"``: only used by ``last_month_trend_pct``; the prior
      month had zero collected, so a percentage change can't be computed.
      ``value`` is 0.0 in this state but the JS must NOT render it as
      "No change" — the trend slot shows "No prior-month baseline" instead.
    """
    value: float | int
    source: Literal["mock", "real", "no_baseline"]


_COLLECTED_SUM = Sum(
    "postings__newlineitempayments__amount",
    filter=Q(postings__entered_in_error__isnull=True),
)


def filed_claims_in_range(start: arrow.Arrow, end: arrow.Arrow) -> Any:
    """Base queryset of filed-or-later claims whose activity date falls in [start, end].

    Trashed claims (``ClaimQueueState.TRASH``) are excluded — they were deleted
    and would silently inflate revenue and acceptance-rate aggregates if left in.
    """
    return Claim.objects.filter(
        current_queue__queue_sort_ordering__gte=ClaimQueueState.FILED,
        modified__range=(start.datetime, end.datetime),
    ).exclude(current_queue__queue_sort_ordering=ClaimQueueState.TRASH)


def aggregate_filed_claims(start: arrow.Arrow, end: arrow.Arrow) -> dict[str, Any]:
    """Count and collected sum for filed claims in window. Single DB query.

    ``Count("id", distinct=True)`` is required because ``_COLLECTED_SUM`` joins
    through ``postings__newlineitempayments`` (two to-many relations). Without
    DISTINCT, ``count`` counts the (claim × postings × payments) joined-row
    fan-out instead of distinct claims, which silently understates
    ``avg_collected`` in ``next_month_projected`` and inflates ``visits`` in
    ``daily_collections``.
    """
    result: dict[str, Any] = filed_claims_in_range(start, end).aggregate(
        count=Count("id", distinct=True),
        total=_COLLECTED_SUM,
    )
    return result


def _mock_summary(key: str) -> SummaryEntry:
    return {"value": mock_overview()["summary"][key], "source": "mock"}


def last_month_collected(now: arrow.Arrow | None = None) -> SummaryEntry:
    start, end = last_month_range(now)
    agg = aggregate_filed_claims(start, end)
    if agg["count"] == 0:
        return _mock_summary("last_month_collected")
    return {"value": float(agg["total"] or Decimal("0")), "source": "real"}


def this_month_collected(now: arrow.Arrow | None = None) -> SummaryEntry:
    start, end = this_month_range(now)
    agg = aggregate_filed_claims(start, end)
    if agg["count"] == 0:
        return _mock_summary("this_month_to_date")
    return {"value": float(agg["total"] or Decimal("0")), "source": "real"}


def compute_trend_pct(current: Decimal, prior: Decimal) -> float | None:
    """Percentage change from ``prior`` to ``current``.

    Returns ``None`` when ``prior`` is zero — there is no baseline to compute
    a percentage against. Callers must NOT substitute 0.0 here, because that
    would render as "0.0% from prior month / No change" in the UI, falsely
    implying the metric was flat when in fact a real value emerged from no
    history.
    """
    if prior == 0:
        return None
    return float((current - prior) / prior * 100)


def last_month_trend_pct(now: arrow.Arrow | None = None) -> SummaryEntry:
    now_arrow = now if now is not None else arrow.utcnow()
    last_start, last_end = last_month_range(now_arrow)
    prior_start, prior_end = last_month_range(now_arrow.shift(months=-1))
    last_agg = aggregate_filed_claims(last_start, last_end)
    prior_agg = aggregate_filed_claims(prior_start, prior_end)
    if last_agg["count"] == 0 and prior_agg["count"] == 0:
        return _mock_summary("last_month_trend_pct")
    pct = compute_trend_pct(
        last_agg["total"] or Decimal("0"),
        prior_agg["total"] or Decimal("0"),
    )
    if pct is None:
        # Prior month had zero collections; can't compute a percentage.
        # JS renders this state as "No prior-month baseline" rather than
        # the misleading "0.0% / No change".
        return {"value": 0.0, "source": "no_baseline"}
    return {"value": pct, "source": "real"}


def next_month_appointment_count(now: arrow.Arrow | None = None) -> SummaryEntry:
    start, end = next_month_range(now)
    count = Appointment.objects.filter(start_time__range=(start.datetime, end.datetime)).count()
    return {"value": count, "source": "real"}


def next_month_projected(
    now: arrow.Arrow | None = None,
    precomputed_appt_count: int | None = None,
) -> SummaryEntry:
    """Project next-month revenue as (appt count) × (avg collected per filed claim, trailing 90d).

    `precomputed_appt_count` lets callers that have already queried the
    appointment count for this `now` pass it in and avoid a duplicate
    ``Appointment.objects...count()`` roundtrip.
    """
    if precomputed_appt_count is None:
        precomputed_appt_count = int(next_month_appointment_count(now)["value"])
    trailing_start, trailing_end = trailing_90_days_range(now)
    agg = aggregate_filed_claims(trailing_start, trailing_end)
    if agg["count"] == 0:
        return _mock_summary("next_month_projected")
    avg_collected = (agg["total"] or Decimal("0")) / Decimal(agg["count"])
    projected = float(Decimal(precomputed_appt_count) * avg_collected)
    return {"value": projected, "source": "real"}


def claim_acceptance_rate(now: arrow.Arrow | None = None) -> SummaryEntry:
    start, end = trailing_30_days_range(now)
    counts = Claim.objects.filter(
        current_queue__queue_sort_ordering__gte=ClaimQueueState.FILED,
        modified__range=(start.datetime, end.datetime),
    ).exclude(
        current_queue__queue_sort_ordering=ClaimQueueState.TRASH,
    ).aggregate(
        filed_total=Count("id"),
        rejected=Count("id", filter=Q(current_queue__queue_sort_ordering=ClaimQueueState.REJECTED)),
    )
    if counts["filed_total"] == 0:
        return _mock_summary("claim_acceptance_rate")
    rate = (counts["filed_total"] - counts["rejected"]) / counts["filed_total"] * 100
    return {"value": rate, "source": "real"}


def daily_collections(now: arrow.Arrow | None = None) -> dict[str, Any]:
    # Trailing 30 days matches the "(trailing month)" chart title in
    # templates/page.html and static/js/main.js. A this_month_range here would
    # produce a sawtooth window that resets on the 1st of each month.
    start, end = trailing_30_days_range(now)
    rows = list(
        filed_claims_in_range(start, end)
        .values("modified__date")
        # ``distinct=True`` because ``_COLLECTED_SUM`` joins through
        # ``postings__newlineitempayments``; without it, ``visits`` would
        # report payment-row counts instead of distinct claim counts.
        .annotate(collected=_COLLECTED_SUM, visits=Count("id", distinct=True))
        .order_by("modified__date")
    )
    if not rows:
        return {"source": "mock", "data": mock_overview()["daily"]}
    return {"source": "real", "data": [
        {
            "date": arrow.get(r["modified__date"]).format("MMM D"),
            "visits": r["visits"],
            "collected": float(r["collected"] or 0),
        }
        for r in rows
    ]}


def monthly_collections(now: arrow.Arrow | None = None) -> dict[str, Any]:
    start, end = trailing_12_months_range(now)
    rows = list(
        filed_claims_in_range(start, end)
        .values("modified__year", "modified__month")
        .annotate(collected=_COLLECTED_SUM)
        .order_by("modified__year", "modified__month")
    )
    if not rows:
        return {"source": "mock", "data": mock_overview()["monthly"]}
    return {"source": "real", "data": [
        {
            "month": arrow.get(r["modified__year"], r["modified__month"], 1).format("MMM"),
            "collected": float(r["collected"] or 0),
        }
        for r in rows
    ]}


def build_overview(now: arrow.Arrow | None = None) -> dict[str, Any]:
    next_month_appt = next_month_appointment_count(now)
    summary: dict[str, SummaryEntry] = {
        "last_month_collected": last_month_collected(now),
        "this_month_collected": this_month_collected(now),
        "next_month_projected": next_month_projected(now, precomputed_appt_count=int(next_month_appt["value"])),
        "claim_acceptance_rate": claim_acceptance_rate(now),
        "last_month_trend_pct": last_month_trend_pct(now),
        "next_month_appt_count": next_month_appt,
    }
    insights = compute_insights(summary)
    return {
        "summary": summary,
        "daily": daily_collections(now),
        "monthly": monthly_collections(now),
        "insights": {"source": "real", "data": insights},
    }
