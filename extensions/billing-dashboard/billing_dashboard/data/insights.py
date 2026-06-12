"""Rule-based insights derived from the Overview summary.

Each rule inspects the summary dict already computed by data/overview.py and
emits zero or one insight entry. Rules do not issue new queries; all inputs
must be present in the summary.

Insight entry shape: {"severity", "title", "description", "tag"}.
Severity values: "info", "warning", "critical".
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from billing_dashboard.data.overview import SummaryEntry


def _value(summary: "dict[str, SummaryEntry]", key: str) -> float | int | None:
    entry = summary.get(key)
    if entry is None:
        return None
    raw = entry["value"]
    return raw if isinstance(raw, (int, float)) else None


def _insight(severity: str, title: str, description: str, tag: str) -> dict[str, str]:
    return {"severity": severity, "title": title, "description": description, "tag": tag}


def compute_insights(summary: "dict[str, SummaryEntry]") -> list[dict[str, str]]:
    out: list[dict[str, str]] = []

    trend = _value(summary, "last_month_trend_pct")
    if trend is not None:
        if trend >= 10:
            out.append(_insight(
                "info",
                "Revenue trending upward",
                f"Monthly collections up {trend:.1f}% vs prior month.",
                "Revenue",
            ))
        elif trend <= -10:
            out.append(_insight(
                "warning",
                "Revenue declining",
                f"Monthly collections down {abs(trend):.1f}% vs prior month.",
                "Revenue",
            ))

    acceptance = _value(summary, "claim_acceptance_rate")
    if acceptance is not None and acceptance < 90:
        out.append(_insight(
            "critical",
            "Claim acceptance rate below target",
            f"Acceptance at {acceptance:.1f}%, below 90% target. Review recent denials.",
            "Claims",
        ))

    appt_count = _value(summary, "next_month_appt_count")
    if appt_count == 0:
        out.append(_insight(
            "info",
            "No appointments scheduled next month",
            "Projected revenue cannot be estimated until appointments are booked.",
            "Volume",
        ))

    this_month = _value(summary, "this_month_collected")
    projected = _value(summary, "next_month_projected")
    if (
        this_month
        and projected
        and projected > 2 * this_month
    ):
        out.append(_insight(
            "info",
            "Projected next month is an estimate",
            "Next-month projection exceeds twice the current month's collections — treat as a directional estimate.",
            "Projection",
        ))

    return out
