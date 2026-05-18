"""Pure data layer for patient_vitals: catalog, queries, aggregation, helpers.

Kept import-light and side-effect-free so tests can patch the single Observation
query helper without touching Django.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Q

from canvas_sdk.v1.data import Observation

PER_CODE_CAP = 100


class UnknownVitalCode(Exception):
    """Raised when a caller passes a code not present in VITAL_CATALOG."""


# Canonical catalog. Each entry maps a stable canonical key (used in the API
# payload and in the request body) to display/icon/unit metadata plus the
# LOINC code and the legacy free-text names found on Observation.name.
#
# LOINC codes are sourced from
#   home-app/api/models/constants/common.py:2798-2823
# Unit conventions from
#   home-app/api/models/constants/common.py:2825-2850
VITAL_CATALOG: dict[str, dict[str, Any]] = {
    "blood_pressure": {
        "loinc": "85354-9",
        "names": {"blood_pressure"},
        "display": "Blood Pressure",
        "unit": "mmHg",
        "icon": "droplet",
        "precision": 0,
        "is_bp": True,
    },
    "pulse": {
        "loinc": "8867-4",
        "names": {"pulse"},
        "display": "Pulse",
        "unit": "bpm",
        "icon": "heart",
        "precision": 0,
    },
    "body_temperature": {
        "loinc": "8310-5",
        "names": {"body_temperature"},
        "display": "Body Temperature",
        "unit": "°F",
        "icon": "thermometer",
        "precision": 1,
    },
    "weight": {
        "loinc": "29463-7",
        "names": {"weight"},
        "display": "Weight",
        "unit": "lbs",
        "icon": "scale",
        "precision": 1,
        "weight_oz": True,
    },
    "height": {
        "loinc": "8302-2",
        "names": {"height"},
        "display": "Height",
        "unit": "in",
        "icon": "ruler",
        "precision": 1,
    },
    "bmi": {
        "loinc": "39156-5",
        "names": {"bmi"},
        "display": "BMI",
        "unit": "",
        "icon": "gauge",
        "precision": 1,
    },
    "oxygen_saturation": {
        "loinc": "59408-5",
        "names": {"oxygen_saturation"},
        "display": "Oxygen Saturation",
        "unit": "%",
        "icon": "lung",
        "precision": 0,
    },
    "respiration_rate": {
        "loinc": "9279-1",
        "names": {"respiration_rate"},
        "display": "Respiration Rate",
        "unit": "bpm",
        "icon": "wave",
        "precision": 0,
    },
    "waist_circumference": {
        "loinc": "56086-2",
        "names": {"waist_circumference"},
        "display": "Waist Circumference",
        "unit": "cm",
        "icon": "ruler-h",
        "precision": 1,
    },
    "head_circumference": {
        "loinc": "9843-4",
        "names": {"head_circumference"},
        "display": "Head Circumference",
        "unit": "cm",
        "icon": "circle-dot",
        "precision": 1,
    },
    "pain_severity": {
        "loinc": "72514-3",
        "names": {"pain_severity"},
        "display": "Pain Severity",
        "unit": "",
        "icon": "alert",
        "precision": 0,
    },
}


# Reverse indices built from VITAL_CATALOG so resolution is O(1) per row
# instead of O(catalog) inside `_resolve_canonicals`. Rebuilt only if the
# catalog is mutated at import time.
_LOINC_TO_CODE: dict[str, str] = {cfg["loinc"]: code for code, cfg in VITAL_CATALOG.items()}
_NAME_TO_CODE: dict[str, str] = {
    name.lower(): code
    for code, cfg in VITAL_CATALOG.items()
    for name in cfg["names"]
}


# ---------- pure helpers ---------------------------------------------------


def _split_bp(value: str | None) -> tuple[float, float] | None:
    """Split a `"<systolic>/<diastolic>"` BP string. Returns None on parse failure."""
    if not value or not isinstance(value, str) or "/" not in value:
        return None
    try:
        systolic_raw, diastolic_raw = value.split("/", 1)
        return float(systolic_raw.strip()), float(diastolic_raw.strip())
    except (ValueError, AttributeError):
        return None


def _oz_to_lbs(value: str | float | None) -> float | None:
    """Convert an oz value (string or number) to pounds. Returns None on failure."""
    if value is None:
        return None
    try:
        return float(value) / 16.0
    except (TypeError, ValueError):
        return None


def _resolve_canonicals(obs: Any) -> set[str]:
    """Map an Observation to the set of canonical catalog keys it represents.

    Resolution order:
      1. The observation's first coding's code, matched against catalog LOINC.
      2. Fallback: ``obs.name`` matched against the catalog's legacy name set.
    """
    loinc = None
    codings = getattr(obs, "codings", None)
    if codings is not None:
        try:
            first = codings.first()
        except AttributeError:
            first = None
        if first is not None:
            loinc = getattr(first, "code", None)

    if loinc and loinc in _LOINC_TO_CODE:
        return {_LOINC_TO_CODE[loinc]}

    name = (getattr(obs, "name", None) or "").strip().lower()
    if name and name in _NAME_TO_CODE:
        return {_NAME_TO_CODE[name]}

    return set()


def _format_display_value(numeric: float, precision: int) -> str:
    """Format a numeric value with the catalog-defined precision."""
    return f"{numeric:.{precision}f}"


def _normalize_point(obs: Any, canon: str) -> dict[str, Any] | None:
    """Extract `recorded_at`, `display_value`, and `chart_value` for one obs+canon.

    `chart_value` is a float (or a `(systolic, diastolic)` tuple for BP) suitable
    for Chart.js. `display_value` is the user-visible string for the tile.
    Returns None if the value can't be parsed.
    """
    cfg = VITAL_CATALOG[canon]
    recorded_at = getattr(obs, "effective_datetime", None)
    if recorded_at is None:
        return None
    iso = (
        recorded_at.isoformat()
        if hasattr(recorded_at, "isoformat")
        else str(recorded_at)
    )

    raw = getattr(obs, "value", None)

    if cfg.get("is_bp"):
        split = _split_bp(raw)
        if split is None:
            return None
        systolic, diastolic = split
        return {
            "recorded_at": iso,
            "display_value": f"{int(systolic)}/{int(diastolic)}",
            "chart_value": (systolic, diastolic),
        }

    if cfg.get("weight_oz"):
        lbs = _oz_to_lbs(raw)
        if lbs is None:
            return None
        return {
            "recorded_at": iso,
            "display_value": _format_display_value(lbs, cfg["precision"]),
            "chart_value": lbs,
        }

    try:
        numeric = float(raw) if raw is not None else None
    except (TypeError, ValueError):
        numeric = None

    if numeric is None:
        display = str(raw) if raw is not None else ""
        return {"recorded_at": iso, "display_value": display, "chart_value": None}

    return {
        "recorded_at": iso,
        "display_value": _format_display_value(numeric, cfg["precision"]),
        "chart_value": numeric,
    }


# ---------- query helper (the only place we touch the ORM) -----------------


def _query_vitals(
    patient_id: str,
    limit_hint: int | None = None,
    *,
    loincs: list[str] | None = None,
    names: list[str] | None = None,
) -> Any:
    """Return a queryset of vital-sign observations, most recent first.

    `.committed()` (inherited from AuditedModel) filters out entries-in-error.
    When ``loincs`` and/or ``names`` are supplied, narrowing happens at the DB
    layer (LOINC join on ``codings`` ∪ free-text match on ``name``) so callers
    don't pay to fetch and discard unrelated vital rows. ``distinct()`` collapses
    the join duplicates that the LOINC OR produces. The outer LIMIT bounds
    Python-side memory.
    """
    qs = (
        Observation.objects.for_patient(patient_id)
        .committed()
        .filter(category="vital-signs", effective_datetime__isnull=False)
        .exclude(name="Vital Signs Panel")
        .select_related("is_member_of")
        .prefetch_related("codings", "components__codings")
        .order_by("-effective_datetime")
    )
    if loincs or names:
        narrow = Q()
        if loincs:
            narrow |= Q(codings__code__in=loincs)
        if names:
            narrow |= Q(name__in=names)
        qs = qs.filter(narrow).distinct()
    if limit_hint is not None:
        qs = qs[:limit_hint]
    return qs


# ---------- public API -----------------------------------------------------


def aggregate_summary(patient_id: str) -> list[dict[str, Any]]:
    """Return one summary entry per catalog code with at least one reading.

    Output is ordered by VITAL_CATALOG insertion order (i.e. clinically grouped).
    """
    n_codes = len(VITAL_CATALOG)
    qs = _query_vitals(
        patient_id,
        limit_hint=n_codes * PER_CODE_CAP,
        loincs=list(_LOINC_TO_CODE.keys()),
        names=list(_NAME_TO_CODE.keys()),
    )

    grouped: dict[str, list[dict[str, Any]]] = {key: [] for key in VITAL_CATALOG}
    for obs in qs:
        for canon in _resolve_canonicals(obs):
            bucket = grouped[canon]
            if len(bucket) >= PER_CODE_CAP:
                continue
            point = _normalize_point(obs, canon)
            if point:
                bucket.append(point)

    out: list[dict[str, Any]] = []
    for canon, points in grouped.items():
        if not points:
            continue
        cfg = VITAL_CATALOG[canon]
        latest = points[0]
        out.append(
            {
                "code": canon,
                "display_name": cfg["display"],
                "icon_key": cfg["icon"],
                "latest_value": latest["display_value"],
                "latest_unit": cfg["unit"],
                "latest_recorded_at": latest["recorded_at"],
                "reading_count": len(points),
            }
        )
    return out


def history_for_code(patient_id: str, code: str | None) -> dict[str, Any]:
    """Return the chart payload for one canonical code.

    For blood pressure, emits two series (Systolic / Diastolic). For other
    codes, a single series labeled with the catalog display name. Points are
    sorted **ascending** by recorded_at so the X axis reads left-to-right.
    """
    if code not in VITAL_CATALOG:
        raise UnknownVitalCode(code or "<missing>")
    cfg = VITAL_CATALOG[code]

    qs = _query_vitals(
        patient_id,
        limit_hint=PER_CODE_CAP,
        loincs=[cfg["loinc"]],
        names=list(cfg["names"]),
    )

    points_desc: list[dict[str, Any]] = []
    for obs in qs:
        # Defense in depth: the DB filter already narrowed by this code's LOINC
        # and names, but verify before normalizing so a row that matched on
        # name alone still resolves to this canonical key (and so tests that
        # stub `_query_vitals` with un-narrowed data still behave correctly).
        if code not in _resolve_canonicals(obs):
            continue
        point = _normalize_point(obs, code)
        if point and point.get("chart_value") is not None:
            points_desc.append(point)

    points_asc = list(reversed(points_desc))

    if cfg.get("is_bp"):
        systolic_pts = [
            {"recorded_at": p["recorded_at"], "value": p["chart_value"][0]}
            for p in points_asc
        ]
        diastolic_pts = [
            {"recorded_at": p["recorded_at"], "value": p["chart_value"][1]}
            for p in points_asc
        ]
        series = [
            {"label": "Systolic", "points": systolic_pts},
            {"label": "Diastolic", "points": diastolic_pts},
        ]
    else:
        single = [
            {"recorded_at": p["recorded_at"], "value": p["chart_value"]}
            for p in points_asc
        ]
        series = [{"label": cfg["display"], "points": single}]

    return {
        "code": code,
        "display_name": cfg["display"],
        "unit": cfg["unit"],
        "series": series,
    }
