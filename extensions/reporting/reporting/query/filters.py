"""Translate declarative filter clauses into Django ORM lookup kwargs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# operator -> Django lookup suffix ("" means exact)
OPERATORS: dict[str, str] = {
    "is": "",
    "is_one_of": "__in",
    "gte": "__gte",
    "gt": "__gt",
    "lte": "__lte",
    "lt": "__lt",
}


@dataclass(frozen=True)
class FilterClause:
    orm_path: str
    operator: str
    values: list[Any]


def build_lookup(clause: FilterClause) -> dict[str, Any]:
    """Return ORM filter kwargs for one clause."""
    if clause.operator not in OPERATORS:
        raise ValueError(f"Unsupported operator: {clause.operator}")
    suffix = OPERATORS[clause.operator]
    key = f"{clause.orm_path}{suffix}"
    if clause.operator == "is_one_of":
        return {key: list(clause.values)}
    return {key: clause.values[0]}


def build_lookups(clauses: list[FilterClause]) -> dict[str, Any]:
    """Combine multiple clauses into a single AND-ed kwargs dict."""
    out: dict[str, Any] = {}
    for clause in clauses:
        out.update(build_lookup(clause))
    return out
