"""Helpers for resolving the set of staff that can be scheduled (and rooms)."""

from __future__ import annotations

import json
from typing import Iterable

from canvas_sdk.v1.data.staff import Staff


def parse_schedulable_roles(secret_value: str) -> list[str]:
    """Parse the ``SCHEDULABLE_STAFF_ROLES`` secret string.

    Accepts either a JSON array (``["MD","NP"]``) or a comma-separated list
    (``MD,NP``). Strips brackets and quotes from each token to be lenient
    with malformed JSON.
    """
    raw = (secret_value or "").strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(r).strip() for r in parsed if str(r).strip()]
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    items = raw.split(",")
    return [r.strip().strip("[]\"'") for r in items if r.strip().strip("[]\"'")]


def get_schedulable_staff(roles: Iterable[str]) -> list[dict]:
    """Return active staff whose role matches one of the given codes.

    Rooms (role code ``RR``) are excluded — they're surfaced separately via
    ``get_room_staff``. Returns ``[{"id": str, "name": str}]`` ordered by name.
    """
    role_list = [r for r in roles if r]
    if not role_list:
        return []
    qs = (
        Staff.objects
        .filter(active=True, roles__internal_code__in=role_list)
        .exclude(roles__internal_code="RR")
        .distinct()
        .order_by("first_name", "last_name")
    )
    return [{"id": str(s.id), "name": s.full_name} for s in qs]


def get_room_staff() -> list[dict]:
    """Return active RR-role staff (rooms), ordered by name."""
    qs = (
        Staff.objects
        .filter(active=True, roles__internal_code="RR")
        .distinct()
        .order_by("first_name", "last_name")
    )
    return [{"id": str(s.id), "name": s.full_name} for s in qs]
