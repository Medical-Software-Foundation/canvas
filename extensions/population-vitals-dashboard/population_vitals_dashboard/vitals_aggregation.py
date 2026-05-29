"""Population-level vitals aggregation for the population vitals dashboard.

This module owns all database access and aggregation logic.  It is intentionally
kept free of HTTP/effect concerns so it can be tested independently.

Design constraints:
- Observation.value is a STRING.  We guard against non-numeric values with a
  regex filter and a Cast annotate before any numeric aggregate runs.
- BP systolic/diastolic come from ObservationComponent.value_quantity, matched
  by component name — NOT from the combined "120/80" value string.
- Aggregation is done entirely in the DB (no Python loops over patients).
- Results are cached via the SDK Cache with a short TTL keyed on the full
  filter combination so repeated UI toggles are cheap.
- Small-cohort suppression: cohorts smaller than MIN_COHORT_SIZE return no
  statistics (PHI guardrail).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from typing import Any

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.v1.data.observation import Observation, ObservationComponent
from canvas_sdk.v1.data.patient import Patient
from django.db.models import (
    Avg,
    Case,
    Count,
    DateTimeField,
    FloatField,
    Func,
    IntegerField,
    Max,
    Min,
    Value,
    When,
)
from logger import log

# ---------- constants --------------------------------------------------------

CACHE_TTL_SECONDS = 120  # 2 minutes

# Numeric-only guard: accept strings that look like floats so the float cast
# never encounters a non-numeric value (e.g. a BP string like "120/80").
NUMERIC_REGEX = r"^-?\d+(\.\d+)?$"

# The five metrics we expose in v1.
# For weight/bmi/height the aggregation runs against Observation.value (cast to float).
# For systolic/diastolic it runs against ObservationComponent.value_quantity.
SCALAR_METRICS: frozenset[str] = frozenset({"weight", "bmi", "height"})
BP_METRICS: frozenset[str] = frozenset({"systolic", "diastolic"})
ALL_METRICS: frozenset[str] = SCALAR_METRICS | BP_METRICS

# Observation.name values used to find the right rows.
METRIC_OBS_NAME: dict[str, str] = {
    "weight": "weight",
    "bmi": "bmi",
    "height": "height",
    "systolic": "blood_pressure",
    "diastolic": "blood_pressure",
}

# Component name fragments for BP components (case-insensitive contains match).
BP_COMPONENT_NAME: dict[str, str] = {
    "systolic": "systolic",
    "diastolic": "diastolic",
}

METRIC_UNITS: dict[str, str] = {
    "weight": "oz",
    "bmi": "",
    "height": "in",
    "systolic": "mmHg",
    "diastolic": "mmHg",
}

METRIC_DISPLAY: dict[str, str] = {
    "weight": "Weight",
    "bmi": "BMI",
    "height": "Height",
    "systolic": "BP Systolic",
    "diastolic": "BP Diastolic",
}

# Number of histogram bins.
HISTOGRAM_BINS = 10

# ---------- custom Postgres aggregate ----------------------------------------


class _PercentileCont(Avg):
    """Postgres PERCENTILE_CONT(0.5) ordered-set aggregate (median).

    Usage:
      qs.aggregate(median=_PercentileCont("numeric_value", fraction=0.5))

    Emits:
      PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY "numeric_value")

    We subclass ``Avg`` (rather than ``Func``) on purpose: the plugin-runner
    sandbox does not allow importing ``django.db.models.Aggregate`` directly,
    and a plain ``Func`` is not recognised by ``.aggregate()`` /
    ``.values().annotate()`` (``contains_aggregate`` is False, and it would be
    added to GROUP BY).  ``Avg`` *is* an ``Aggregate``, so subclassing it gives
    us all the aggregate machinery for free; we only override the SQL function
    and template.  ``fraction`` is stored in ``self.extra`` so the base
    ``Func.as_sql`` interpolates it into the template.
    """

    function = "PERCENTILE_CONT"
    name = "PercentileCont"
    template = "%(function)s(%(fraction)s) WITHIN GROUP (ORDER BY %(expressions)s)"
    output_field = FloatField()

    def __init__(self, expression: str, fraction: float = 0.5, **kwargs: Any) -> None:
        super().__init__(expression, **kwargs)
        self.extra["fraction"] = fraction


class _CastToFloat(Func):
    """Cast a (string) column to a float, DB-side.

    The plugin-runner sandbox does not allow importing
    ``django.db.models.functions.Cast``, so we express the cast directly with
    the allowed ``Func`` primitive.

    Emits: CAST(<expression> AS DOUBLE PRECISION)
    """

    function = "CAST"
    template = "%(function)s(%(expressions)s AS DOUBLE PRECISION)"
    output_field = FloatField()


class _TruncMonth(Func):
    """Truncate a datetime column to the start of its month, DB-side.

    The plugin-runner sandbox does not allow importing
    ``django.db.models.functions.TruncMonth``, so we express it directly with
    the allowed ``Func`` primitive and Postgres ``DATE_TRUNC``.

    Emits: DATE_TRUNC('month', <expression>)
    """

    function = "DATE_TRUNC"
    template = "%(function)s('month', %(expressions)s)"
    output_field = DateTimeField()


# ---------- cohort helpers ---------------------------------------------------


def _subtract_years(d: date, years: int) -> date:
    """Return ``d`` shifted back ``years`` years.

    ``date.replace(year=...)`` raises on Feb 29 when the target year is not a
    leap year; clamp to Feb 28 in that case so the endpoint never crashes.
    """
    try:
        return d.replace(year=d.year - years)
    except ValueError:
        # Only Feb 29 → non-leap year hits this; clamp to Feb 28.
        return d.replace(year=d.year - years, day=28)


def _build_cohort_qs(
    min_age: int | None,
    max_age: int | None,
    sex: str | None,
) -> Any:
    """Return a Patient queryset filtered by age bounds and sex."""
    today = date.today()
    qs = Patient.objects.filter(deceased=False)

    if min_age is not None:
        # patient must be AT LEAST min_age → birth_date <= today - min_age years
        cutoff = _subtract_years(today, min_age)
        qs = qs.filter(birth_date__lte=cutoff)

    if max_age is not None:
        # patient must be AT MOST max_age → birth_date > today - (max_age + 1) years
        cutoff = _subtract_years(today, max_age + 1)
        qs = qs.filter(birth_date__gt=cutoff)

    if sex and sex.upper() != "ALL":
        qs = qs.filter(sex_at_birth=sex.upper())

    return qs


# ---------- metric aggregation -----------------------------------------------
#
# Both scalar metrics (Observation.value) and BP metrics
# (ObservationComponent.value_quantity) reduce to a numeric-value-annotated
# queryset.  Everything downstream — count/mean/median, histogram and monthly
# trend — is shared via ``_compute_stats``.  Counting uses ``Count("pk")`` (the
# primary key, ``dbid`` on both models) so it works regardless of whether the
# model exposes an ``id`` field.


def _aggregate_scalar(
    cohort_qs: Any,
    metric: str,
    start: datetime,
    end: datetime,
) -> dict[str, Any] | None:
    """Aggregate a scalar metric (weight/bmi/height) for a cohort.

    ``cohort_qs`` is a Patient queryset used as a subquery (``patient__in``) so
    the cohort filter stays in the database — we never materialise patient IDs.
    """
    qs = Observation.objects.filter(
        patient__in=cohort_qs,
        name__iexact=METRIC_OBS_NAME[metric],
        category="vital-signs",
        entered_in_error__isnull=True,
        effective_datetime__gte=start,
        effective_datetime__lte=end,
        value__regex=NUMERIC_REGEX,
    ).annotate(numeric_value=_CastToFloat("value"))

    return _compute_stats(qs, metric, "effective_datetime")


def _aggregate_bp(
    cohort_qs: Any,
    metric: str,
    start: datetime,
    end: datetime,
) -> dict[str, Any] | None:
    """Aggregate BP systolic or diastolic from ObservationComponent for a cohort.

    BP components store the numeric value in ``value_quantity``.  We filter the
    components directly, traversing to the parent observation for the cohort,
    name, category, retraction and date-window conditions — a single queryset,
    no intermediate observation-ID list.
    """
    qs = ObservationComponent.objects.filter(
        observation__patient__in=cohort_qs,
        observation__name__iexact="blood_pressure",
        observation__category="vital-signs",
        observation__entered_in_error__isnull=True,
        observation__effective_datetime__gte=start,
        observation__effective_datetime__lte=end,
        name__icontains=BP_COMPONENT_NAME[metric],
        value_quantity__regex=NUMERIC_REGEX,
    ).annotate(numeric_value=_CastToFloat("value_quantity"))

    return _compute_stats(qs, metric, "observation__effective_datetime")


def _compute_stats(qs: Any, metric: str, date_field: str) -> dict[str, Any] | None:
    """Compute count/mean/median, histogram and monthly trend for a queryset.

    ``qs`` must already be annotated with a ``numeric_value`` float expression.
    ``date_field`` is the field path to bucket the monthly trend on.
    Returns None if there are no numeric values.
    """
    # count, mean and median in a single query.
    agg = qs.aggregate(
        count=Count("pk"),
        mean=Avg("numeric_value"),
        median=_PercentileCont("numeric_value", fraction=0.5),
    )

    count = agg["count"] or 0
    if count == 0:
        return None

    return {
        "count": count,
        "mean": round(agg["mean"], 2) if agg["mean"] is not None else None,
        "median": round(agg["median"], 2) if agg["median"] is not None else None,
        "unit": METRIC_UNITS[metric],
        "histogram": _build_histogram(qs, count),
        "monthly_trend": _build_monthly_trend(qs, date_field),
    }


def _build_histogram(qs: Any, count: int) -> list[dict[str, Any]]:
    """Build a HISTOGRAM_BINS-bin histogram from a numeric_value-annotated queryset.

    Uses two queries total: one for the min/max bounds, then one conditional-count
    aggregate that tallies every bin at once (instead of one COUNT per bin).
    """
    bounds = qs.aggregate(min_val=Min("numeric_value"), max_val=Max("numeric_value"))
    min_val = bounds["min_val"]
    max_val = bounds["max_val"]

    if min_val is None or max_val is None or min_val == max_val:
        # All values identical or no data: single bin.
        return [{"min": min_val, "max": max_val, "count": count}]

    bin_width = (max_val - min_val) / HISTOGRAM_BINS
    edges = [
        (min_val + i * bin_width, min_val + (i + 1) * bin_width) for i in range(HISTOGRAM_BINS)
    ]

    # One aggregate with a conditional Count per bin. The last bin is inclusive
    # of max_val; all others are half-open [lo, hi).
    bin_counts: dict[str, Any] = {}
    for i, (lo, hi) in enumerate(edges):
        if i < HISTOGRAM_BINS - 1:
            condition = When(numeric_value__gte=lo, numeric_value__lt=hi, then=Value(1))
        else:
            condition = When(numeric_value__gte=lo, numeric_value__lte=hi, then=Value(1))
        bin_counts[f"bin_{i}"] = Count(Case(condition, output_field=IntegerField()))

    counts = qs.aggregate(**bin_counts)

    return [
        {"min": round(lo, 2), "max": round(hi, 2), "count": counts[f"bin_{i}"]}
        for i, (lo, hi) in enumerate(edges)
    ]


def _build_monthly_trend(qs: Any, date_field: str) -> list[dict[str, Any]]:
    """Return median-per-month data points for a numeric_value-annotated queryset.

    ``date_field`` is the path to the datetime to bucket on (e.g.
    ``effective_datetime`` for observations, ``observation__effective_datetime``
    for components).
    """
    monthly = (
        qs.annotate(month=_TruncMonth(date_field))
        .values("month")
        .annotate(
            median=_PercentileCont("numeric_value", fraction=0.5),
            count=Count("pk"),
        )
        .order_by("month")
    )

    return [
        {
            "month": row["month"].strftime("%Y-%m") if row["month"] else None,
            "median": round(row["median"], 2) if row["median"] is not None else None,
            "count": row["count"],
        }
        for row in monthly
    ]


# ---------- public API -------------------------------------------------------


def _parse_min_cohort_size(secrets: dict[str, str]) -> int:
    """Parse MIN_COHORT_SIZE from secrets.  Fails closed on missing or invalid."""
    raw = secrets.get("MIN_COHORT_SIZE", "").strip()
    if not raw:
        return 11  # default
    try:
        value = int(raw)
    except ValueError:
        log.error(
            "MIN_COHORT_SIZE secret is not a valid integer (got %r); "
            "defaulting to 11 (fail-closed).",
            raw,
        )
        return 11
    if value < 1:
        log.error(
            "MIN_COHORT_SIZE secret is < 1 (got %d); defaulting to 11 (fail-closed).",
            value,
        )
        return 11
    return value


def get_stats(
    metric: str,
    min_age: int | None,
    max_age: int | None,
    sex: str | None,
    start: datetime,
    end: datetime,
    secrets: dict[str, str],
) -> dict[str, Any]:
    """Return aggregate statistics for a metric and cohort.

    Returns a dict with either a ``data`` key (statistics) or an ``error`` key
    (cohort too small, unknown metric, etc.).

    Caches results for CACHE_TTL_SECONDS to keep repeated filter toggles cheap.
    """
    if metric not in ALL_METRICS:
        return {"error": f"unknown metric: {metric!r}"}

    min_cohort_size = _parse_min_cohort_size(secrets)

    # Build a stable cache key from all filter parameters.
    cache_key_src = (
        f"stats:{metric}:{min_age}:{max_age}:{sex}:{start.isoformat()}:{end.isoformat()}"
    )
    cache_key = hashlib.sha256(cache_key_src.encode()).hexdigest()[:32]

    cache = get_cache()

    def _compute() -> dict[str, Any]:
        cohort_qs = _build_cohort_qs(min_age, max_age, sex)
        cohort_count = cohort_qs.count()

        if cohort_count < min_cohort_size:
            log.info(
                "Population vitals: cohort too small (%d < %d) for metric=%s",
                cohort_count,
                min_cohort_size,
                metric,
            )
            return {
                "error": "cohort_too_small",
                "cohort_count": cohort_count,
                "min_cohort_size": min_cohort_size,
            }

        # Pass the cohort queryset itself (used as a subquery) rather than a
        # materialised list of patient IDs — keeps the cohort filter in the DB.
        if metric in SCALAR_METRICS:
            data = _aggregate_scalar(cohort_qs, metric, start, end)
        else:
            data = _aggregate_bp(cohort_qs, metric, start, end)

        if data is None:
            return {"error": "no_data", "cohort_count": cohort_count}

        return {
            "data": {
                "metric": metric,
                "display_name": METRIC_DISPLAY[metric],
                "cohort_count": cohort_count,
                **data,
            }
        }

    result: dict[str, Any] = cache.get_or_set(
        cache_key, _compute, timeout_seconds=CACHE_TTL_SECONDS
    )
    return result


def get_default_date_window() -> tuple[datetime, datetime]:
    """Return (start, end) for the default 12-month window ending now."""
    now = datetime.now(UTC)
    start = (
        now.replace(year=now.year - 1)
        if (now.month, now.day) != (2, 29)
        else now.replace(year=now.year - 1, day=28)
    )
    return start, now
