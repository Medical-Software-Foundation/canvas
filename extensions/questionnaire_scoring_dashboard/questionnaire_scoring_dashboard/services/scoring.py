"""Pure transform: raw survey-Observation rows -> per-instrument series.

Takes the plain dicts produced by the data layer (see data/observations.py)
so it can be unit-tested without any database.
"""

from __future__ import annotations

import arrow

from questionnaire_scoring_dashboard.config import resolve_instrument


def _row_date(row: dict) -> str:
    """Resolve a YYYY-MM-DD date: note DOS -> effective_datetime -> created.

    The note's date-of-service is when the questionnaire was administered, which
    is the clinically meaningful date. Questionnaire-result observations carry
    the scoring time (or none) in effective_datetime, so the note DOS comes first.
    """
    value = row.get("note_dos") or row.get("effective_datetime") or row.get("created")
    return arrow.get(value).format("YYYY-MM-DD")


def _to_float(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def build_series(rows: list[dict]) -> dict[str, list[dict]]:
    """Group rows by resolved instrument label, drop non-numeric values,
    and sort each instrument's points ascending by date.

    Returns: {label: [{"date": "YYYY-MM-DD", "value": float}, ...]}
    """
    series: dict[str, list[dict]] = {}
    for row in rows:
        value = _to_float(row.get("value"))
        if value is None:
            continue
        label = resolve_instrument(row.get("name") or "").label
        point = {"date": _row_date(row), "value": value}
        series.setdefault(label, []).append(point)

    # Sort by date and collapse to one point per date (an instrument can be
    # double-scored on the same day - e.g. a native instance score plus this
    # plugin's - which would otherwise show as duplicate points).
    deduped: dict[str, list[dict]] = {}
    for label, points in series.items():
        points.sort(key=lambda p: p["date"])
        by_date: dict[str, dict] = {}
        for point in points:
            by_date[point["date"]] = point  # later same-date point wins
        deduped[label] = list(by_date.values())
    return deduped
