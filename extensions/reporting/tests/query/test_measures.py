# tests/query/test_measures.py
from __future__ import annotations

from reporting.query.measures import (
    CountMeasure,
    RatioMeasure,
    count_specs,
    compute_value,
)


def test_count_measure_declares_one_count_spec():
    m = CountMeasure(key="total", label="Total appointments")
    specs = count_specs(m)
    assert list(specs.keys()) == ["total__all"]
    assert specs["total__all"] is None  # None filter == count everything


def test_count_where_measure_declares_filtered_count():
    m = CountMeasure(key="noshows", label="No-shows", where={"status__in": ["noshowed", "cancelled"]})
    specs = count_specs(m)
    assert specs == {"noshows__all": {"status__in": ["noshowed", "cancelled"]}}


def test_ratio_measure_declares_numerator_and_denominator_specs():
    m = RatioMeasure(
        key="no_show_rate",
        label="No-show rate (%)",
        numerator_where={"status__in": ["noshowed", "cancelled"]},
        as_percent=True,
    )
    specs = count_specs(m)
    assert specs == {
        "no_show_rate__num": {"status__in": ["noshowed", "cancelled"]},
        "no_show_rate__den": None,
    }


def test_compute_count_value_reads_named_count():
    m = CountMeasure(key="total", label="Total")
    assert compute_value(m, {"total__all": 42}) == 42


def test_compute_ratio_as_percent_rounds_to_one_dp():
    m = RatioMeasure(key="r", label="rate", numerator_where={"x": 1}, as_percent=True)
    assert compute_value(m, {"r__num": 3, "r__den": 24}) == 12.5


def test_compute_ratio_zero_denominator_is_zero():
    m = RatioMeasure(key="r", label="rate", numerator_where={"x": 1}, as_percent=True)
    assert compute_value(m, {"r__num": 0, "r__den": 0}) == 0.0
