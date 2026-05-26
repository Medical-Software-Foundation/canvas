"""Payer tab data builder — per-payer aggregation against Claim.

Groups filed-or-later claims by `coverages__payer_name` and aggregates at the
DB level: collected amount, total claim count, rejected claim count. Single
query; no per-claim Python iteration.
"""

from __future__ import annotations

from typing import Any

import arrow
from canvas_sdk.v1.data.claim import Claim
from django.db.models import Count, Q, Sum

from billing_dashboard.data.claim_queue import ClaimQueueState
from billing_dashboard.data.mock import payer_analysis as mock_payer
from billing_dashboard.data.windows import trailing_90_days_range


def build_payer(now: arrow.Arrow | None = None) -> dict[str, Any]:
    start, end = trailing_90_days_range(now)
    rows = list(
        Claim.objects.filter(
            current_queue__queue_sort_ordering__gte=ClaimQueueState.FILED,
            modified__range=(start.datetime, end.datetime),
        )
        .exclude(coverages__payer_name="")
        .values("coverages__payer_name")
        .annotate(
            collected=Sum(
                "postings__newlineitempayments__amount",
                filter=Q(postings__entered_in_error__isnull=True),
            ),
            total_claims=Count("id"),
            rejected_claims=Count("id", filter=Q(current_queue__queue_sort_ordering=ClaimQueueState.REJECTED)),
        )
    )

    if not rows:
        return {"payers": {"source": "mock", "data": mock_payer()["payers"]}}

    data = []
    for r in rows:
        name = r["coverages__payer_name"]
        if not name:
            continue
        total = r["total_claims"] or 0
        rejected = r["rejected_claims"] or 0
        accepted = total - rejected
        acceptance_rate = (accepted / total * 100) if total else 0.0
        data.append({
            "name": name,
            "collected": float(r["collected"] or 0),
            "acceptance_rate": round(acceptance_rate, 2),
            "cms_delta": None,
        })
    if not data:
        return {"payers": {"source": "mock", "data": mock_payer()["payers"]}}
    data.sort(key=lambda row: row["collected"], reverse=True)
    return {"payers": {"source": "real", "data": data}}
