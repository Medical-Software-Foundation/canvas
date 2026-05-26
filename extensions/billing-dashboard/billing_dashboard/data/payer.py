"""Payer tab data builder — per-payer aggregation against Claim.

Groups filed-or-later claims by ``current_coverage__payer_name`` (the claim's
*primary* coverage's payer) and aggregates at the DB level: collected amount,
total claim count, rejected claim count. Single query; no per-claim Python
iteration.

Why ``current_coverage`` (singular FK) and not ``coverages`` (M2M reverse): a
claim with both primary and secondary coverage (e.g., Medicare + supplemental)
appears in the M2M join once per coverage. Grouping by ``coverages__payer_name``
would attribute the claim's full collected amount to BOTH payers, inflating
revenue and claim counts. The repo's sample-sql/financial/ar_by_insurance_payer
uses the equivalent ``cc.id = c.current_coverage_id`` filter for the same
reason.

``Count("id", distinct=True)`` is required on top of that because the ``Sum``
joins through ``postings__newlineitempayments`` (two more to-many relations),
which would otherwise fan ``total_claims`` out by the per-claim payment count.
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
        .exclude(current_coverage__payer_name="")
        .values("current_coverage__payer_name")
        .annotate(
            collected=Sum(
                "postings__newlineitempayments__amount",
                filter=Q(postings__entered_in_error__isnull=True),
            ),
            total_claims=Count("id", distinct=True),
            rejected_claims=Count(
                "id",
                filter=Q(current_queue__queue_sort_ordering=ClaimQueueState.REJECTED),
                distinct=True,
            ),
        )
    )

    if not rows:
        return {"payers": {"source": "mock", "data": mock_payer()["payers"]}}

    data = []
    for r in rows:
        name = r["current_coverage__payer_name"]
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
