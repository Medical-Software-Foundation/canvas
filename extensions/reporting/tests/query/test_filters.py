# tests/query/test_filters.py
from __future__ import annotations

import pytest

from reporting.query.filters import FilterClause, OPERATORS, build_lookup


def test_is_operator_single_value():
    clause = FilterClause(orm_path="status", operator="is", values=["noshowed"])
    assert build_lookup(clause) == {"status": "noshowed"}


def test_is_one_of_uses_in_lookup():
    clause = FilterClause(orm_path="status", operator="is_one_of", values=["noshowed", "cancelled"])
    assert build_lookup(clause) == {"status__in": ["noshowed", "cancelled"]}


def test_numeric_operators():
    assert build_lookup(FilterClause("age", "gte", [18])) == {"age__gte": 18}
    assert build_lookup(FilterClause("age", "lt", [65])) == {"age__lt": 65}


def test_unknown_operator_raises():
    with pytest.raises(ValueError):
        build_lookup(FilterClause("status", "matches_regex", ["x"]))


def test_operators_registry_is_closed_set():
    assert set(OPERATORS) == {"is", "is_one_of", "gte", "gt", "lte", "lt"}
