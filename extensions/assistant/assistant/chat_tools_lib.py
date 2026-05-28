"""Helpers and constants for `assistant.chat_tools` tool modules.

Lives outside the `chat_tools` package so tool modules can import from here
without triggering re-evaluation of `chat_tools/__init__.py`. Under
RestrictedPython the sandbox re-evaluates `__init__.py` files when a submodule
imports back into its own package mid-load, which causes infinite recursion
and ultimately an empty registry. Keeping shared helpers in a sibling module
breaks that cycle.
"""

from typing import Any

from pydantic import BaseModel

DEFAULT_RESULT_LIMIT = 10
MAX_RESULT_LIMIT = 50


def apply_filter_args(qs: Any, args: BaseModel, lookups: dict[str, str]) -> Any:
    """Apply optional args to a queryset via a `{field_name: lookup_path}` map.

    Each entry maps a pydantic field name on `args` to a Django ORM lookup path
    (e.g. `"first_name": "first_name__iexact"`, `"date_from": "start_time__gte"`,
    `"patient_id": "patient__id"`). Values that are `None` or an empty list
    (for `__in` filters) are skipped, so callers don't have to gate them.
    """
    filters: dict[str, Any] = {}
    for field_name, lookup_path in lookups.items():
        value = getattr(args, field_name, None)
        if value is None or value == []:
            continue
        filters[lookup_path] = value
    return qs.filter(**filters)
