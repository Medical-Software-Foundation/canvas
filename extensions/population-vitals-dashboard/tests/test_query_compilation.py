"""Query-compilation tests for the aggregation layer.

The rest of the suite mocks the ORM, which means it cannot catch the class of
bugs that actually broke this plugin in the sandbox:

  * a blocked import (``Cast`` / ``TruncMonth``) — the module fails to load;
  * a ``Func`` used where an aggregate is required — "X is not an aggregate
    expression";
  * a wrong field name (``Count("id")`` on ``ObservationComponent``, which has
    no ``id`` field) — ``FieldError``.

All three surface at *query compilation* time, not execution time.  By forcing
Django to compile the exact queryset shapes the aggregation layer builds
(``str(queryset.query)``) we exercise field resolution, aggregate detection and
SQL generation against the real SDK models — no live database needed.

These query shapes intentionally mirror ``vitals_aggregation``; if you change a
query there, update it here too.
"""

from __future__ import annotations

from canvas_sdk.v1.data.observation import Observation, ObservationComponent
from canvas_sdk.v1.data.patient import Patient
from django.db.models import Avg, Case, Count, IntegerField, Max, Min, Value, When

from population_vitals_dashboard.vitals_aggregation import (
    _CastToFloat,
    _PercentileCont,
    _TruncMonth,
)


def _compile(queryset: object) -> str:
    """Return the compiled SQL for a queryset (raises on field/aggregate errors)."""
    return str(queryset.query)  # type: ignore[attr-defined]


def _cohort() -> object:
    """A Patient cohort queryset, used as a subquery (mirrors _build_cohort_qs)."""
    return Patient.objects.filter(deceased=False)


# ── scalar metric (Observation.value) ─────────────────────────────────────────


def test_scalar_combined_aggregate_query_compiles() -> None:
    """count(pk)/mean/median compile together against the cohort subquery."""
    qs = Observation.objects.filter(
        patient__in=_cohort(), name__iexact="weight", category="vital-signs"
    ).annotate(numeric_value=_CastToFloat("value"))

    agg_sql = _compile(
        qs.values("name").annotate(
            count=Count("pk"),
            mean=Avg("numeric_value"),
            median=_PercentileCont("numeric_value", fraction=0.5),
        )
    )
    assert "PERCENTILE_CONT(0.5) WITHIN GROUP" in agg_sql
    assert "AS DOUBLE PRECISION" in agg_sql  # the cast
    assert "AVG" in agg_sql
    # Cohort is a subquery, not a giant IN-list of literals.
    assert "SELECT" in agg_sql.split("WHERE", 1)[-1] or "IN (SELECT" in agg_sql


def test_scalar_conditional_histogram_query_compiles() -> None:
    """The single-aggregate conditional-count histogram compiles."""
    qs = Observation.objects.filter(name__iexact="weight").annotate(
        numeric_value=_CastToFloat("value")
    )
    bin_counts = {}
    for i, (lo, hi) in enumerate([(100.0, 150.0), (150.0, 200.0)]):
        bin_counts[f"bin_{i}"] = Count(
            Case(
                When(numeric_value__gte=lo, numeric_value__lt=hi, then=Value(1)),
                output_field=IntegerField(),
            )
        )
    hist_sql = _compile(qs.values("name").annotate(**bin_counts))
    assert "COUNT(CASE WHEN" in hist_sql
    assert "AS DOUBLE PRECISION" in hist_sql


def test_scalar_histogram_bounds_query_compiles() -> None:
    """Min/Max bounds over the cast annotation compile."""
    qs = Observation.objects.filter(name__iexact="weight").annotate(
        numeric_value=_CastToFloat("value")
    )
    bounds_sql = _compile(
        qs.values("name").annotate(lo=Min("numeric_value"), hi=Max("numeric_value"))
    )
    assert "MIN(" in bounds_sql
    assert "MAX(" in bounds_sql


def test_scalar_monthly_trend_query_compiles() -> None:
    """The monthly-trend grouping (DATE_TRUNC + median + count(pk)) compiles."""
    qs = Observation.objects.filter(name__iexact="weight").annotate(
        numeric_value=_CastToFloat("value")
    )
    trend_sql = _compile(
        qs.annotate(month=_TruncMonth("effective_datetime"))
        .values("month")
        .annotate(median=_PercentileCont("numeric_value", fraction=0.5), count=Count("pk"))
        .order_by("month")
    )
    assert "DATE_TRUNC('month'" in trend_sql
    assert "PERCENTILE_CONT" in trend_sql


# ── blood-pressure metric (ObservationComponent via parent traversal) ─────────


def test_bp_aggregate_query_compiles_via_parent_traversal() -> None:
    """BP aggregation filters components, traversing to the parent observation."""
    qs = ObservationComponent.objects.filter(
        observation__patient__in=_cohort(),
        observation__name__iexact="blood_pressure",
        observation__category="vital-signs",
        name__icontains="systolic",
    ).annotate(numeric_value=_CastToFloat("value_quantity"))

    agg_sql = _compile(
        qs.values("name").annotate(
            count=Count("pk"),
            mean=Avg("numeric_value"),
            median=_PercentileCont("numeric_value", fraction=0.5),
        )
    )
    assert "PERCENTILE_CONT(0.5) WITHIN GROUP" in agg_sql
    # Count("pk") resolves to the component's dbid primary key.
    assert "dbid" in agg_sql
    # Traversal produces a join to the observation table.
    assert "observation" in agg_sql.lower()


def test_bp_monthly_trend_query_compiles() -> None:
    """BP monthly trend buckets via the parent observation's effective_datetime."""
    qs = ObservationComponent.objects.filter(
        observation__patient__in=_cohort(), name__icontains="diastolic"
    ).annotate(numeric_value=_CastToFloat("value_quantity"))
    trend_sql = _compile(
        qs.annotate(month=_TruncMonth("observation__effective_datetime"))
        .values("month")
        .annotate(median=_PercentileCont("numeric_value", fraction=0.5), count=Count("pk"))
        .order_by("month")
    )
    assert "DATE_TRUNC('month'" in trend_sql
