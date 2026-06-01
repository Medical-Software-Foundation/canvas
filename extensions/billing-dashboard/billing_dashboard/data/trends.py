"""Trends tab data builder — CPT-level aggregation against BillingLineItem.

Uses BillingLineItem because CPT is a BLI attribute. BLI.charge is the charged
amount; the column is labeled "Your Avg Charge" and compared against CMS.
Posted-amount-per-CPT is deferred (would require Posting→CPT join without
importing Posting).
"""

from __future__ import annotations

from typing import Any

import arrow
from canvas_sdk.v1.data.billing import BillingLineItem, BillingLineItemStatus
from canvas_sdk.v1.data.charge_description_master import ChargeDescriptionMaster
from django.db.models import Avg, Count, Min

from billing_dashboard.data.cms_rates import (
    CMS_PRIMARY_BENCHMARK,
    get_cms_rate,
    get_cpt_description,
)
from billing_dashboard.data.windows import (
    trailing_12_months_range,
    trailing_90_days_range,
)


def cpt_codes(now: arrow.Arrow | None = None) -> dict[str, Any]:
    start, end = trailing_90_days_range(now)
    rows = list(
        BillingLineItem.objects.filter(
            created__range=(start.datetime, end.datetime),
            status=BillingLineItemStatus.ACTIVE,
        )
        .values("cpt")
        .annotate(
            your_avg_charge=Avg("charge"),
            volume=Count("id"),
            sample_description=Min("description"),
        )
        .order_by("-volume")[:10]
    )
    if not rows:
        return {"source": "real", "data": []}

    cpt_list = [r["cpt"] for r in rows]
    # Ascending effective_date so the *newest* CDM row per CPT is iterated last
    # and wins ``dict()``'s last-write-wins collapse. Reversing this to ``-effective_date``
    # would silently surface the oldest description for any CPT with revisions.
    cdm_descriptions = dict(
        ChargeDescriptionMaster.objects
        .filter(cpt_code__in=cpt_list)
        .order_by("cpt_code", "effective_date")
        .values_list("cpt_code", "short_name")
    )

    return {
        "source": "real",
        "data": [
            {
                "code": r["cpt"],
                "description": (
                    cdm_descriptions.get(r["cpt"])
                    or r.get("sample_description")
                    or get_cpt_description(r["cpt"])
                    or ""
                ),
                "your_avg_charge": float(r["your_avg_charge"]) if r["your_avg_charge"] else 0.0,
                "cms_rate": get_cms_rate(r["cpt"]),
                "trend": 0,
            }
            for r in rows
        ],
    }


def monthly_avg(now: arrow.Arrow | None = None) -> dict[str, Any]:
    start, end = trailing_12_months_range(now)
    rows = list(
        BillingLineItem.objects.filter(
            created__range=(start.datetime, end.datetime),
            status=BillingLineItemStatus.ACTIVE,
        )
        .values("created__year", "created__month")
        .annotate(avg_charge=Avg("charge"))
        .order_by("created__year", "created__month")
    )
    if not rows:
        return {"source": "real", "data": []}
    return {
        "source": "real",
        "data": [
            {
                "month": arrow.get(r["created__year"], r["created__month"], 1).format("MMM YYYY"),
                "avg_charge": float(r["avg_charge"]) if r["avg_charge"] else 0.0,
            }
            for r in rows
        ],
    }


def build_trends(now: arrow.Arrow | None = None) -> dict[str, Any]:
    return {
        "cpt_codes": cpt_codes(now),
        "monthly_avg": monthly_avg(now),
        "cms_benchmark": CMS_PRIMARY_BENCHMARK,
    }
