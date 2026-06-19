"""Pure transform: raw survey-Observation rows -> per-instrument series.

Takes the plain dicts produced by the data layer (see data/observations.py)
so it can be unit-tested without any database.
"""

from __future__ import annotations

import re

import arrow

from questionnaire_scoring_dashboard.config import Instrument, resolve_instrument

# Canvas appends a "(vN)" suffix to a questionnaire's name each time it is
# edited (e.g. "PHQ-2 (v28)"). The suffix is the only part of the name that
# changes across versions, so we strip it to recover the stable instrument name.
_VERSION_SUFFIX = re.compile(r"\s*\(v\d+\)\s*$")


def _base_name(name: str) -> str:
    """Strip Canvas's trailing version suffix: 'PHQ-2 (v28)' -> 'PHQ-2'."""
    return _VERSION_SUFFIX.sub("", name).strip()


def _resolve(base_name: str, code: str) -> Instrument:
    """Resolve to a known Instrument by the version-stripped name, falling back
    to the questionnaire coding when the name is unrecognized.

    config.resolve_instrument returns a generic Instrument(name, None) when no
    known instrument matches; a populated max_score marks a real match.
    """
    inst = resolve_instrument(base_name)
    if inst.max_score is None and code:
        by_code = resolve_instrument(code)
        if by_code.max_score is not None:
            return by_code
    return inst


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
    """Group scored rows into one trend per instrument, dropping non-numeric
    values and sorting each instrument's points ascending by date.

    Instruments are keyed by their questionnaire coding `code` (stable across
    versions), so "PHQ-2" and "PHQ-2 (v28)" - which share a code - land on one
    trend. Two guards keep the grouping honest:

    - A code shared by more than one distinct instrument name is a generic
      scoring code (e.g. several questionnaires all coded "default_score") and
      must NOT collapse unrelated instruments together; those fall back to the
      version-stripped name.
    - A row with no coding falls back to its version-stripped name.

    Returns: {label: [{"date": "YYYY-MM-DD", "value": float}, ...]}
    """
    parsed: list[dict] = []
    names_per_code: dict[str, set[str]] = {}
    for row in rows:
        value = _to_float(row.get("value"))
        if value is None:
            continue
        base = _base_name(row.get("name") or "")
        code = (row.get("code") or "").strip()
        parsed.append(
            {"code": code, "base": base, "point": {"date": _row_date(row), "value": value}}
        )
        if code:
            names_per_code.setdefault(code, set()).add(base)

    # A grouping key per row: the code when it uniquely identifies one
    # instrument, otherwise the version-stripped name.
    series: dict[str, list[dict]] = {}
    for item in parsed:
        code = item["code"]
        if code and len(names_per_code[code]) == 1:
            label = _resolve(item["base"], code).label
        else:
            label = _resolve(item["base"], "").label
        series.setdefault(label, []).append(item["point"])

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
