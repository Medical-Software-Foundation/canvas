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


ROOM_ROLE_CODE = "RR"


def get_schedulable_staff_and_rooms(
    roles: Iterable[str],
) -> tuple[list[dict], list[dict]]:
    """Return ``(providers, rooms)`` from a single Staff query.

    Providers are active staff holding one of ``roles`` and *not* the room
    role. Rooms are active staff holding ``RR``, returned whether or not ``RR``
    appears in ``roles`` — rooms are configured independently of the provider
    dropdown, so the room list must not depend on the roles secret.

    Both lists are ``[{"id": str, "name": str}]`` ordered by name, and are
    disjoint: a staff member holding both ``RR`` and a clinical role counts as
    a room, matching the previous ``.exclude(roles__internal_code="RR")``.

    Two design notes, since both look like mistakes otherwise:

    * ``roles__internal_code`` is selected deliberately, which fans the join
      out to one row per (staff, role) pair. That's the point — the rows are
      folded back together below, and that's what lets one query answer both
      questions. It's also why there's no ``.distinct()``: the old queries
      needed it precisely because they joined ``roles`` without selecting from
      it, so a staff member holding two matching roles came back twice.
    * ``name`` mirrors ``Staff.full_name`` (``first_name`` + ``last_name``)
      rather than fetching whole model instances for two string fields.
    """
    role_list = {r for r in roles if r}
    wanted = role_list | {ROOM_ROLE_CODE}

    rows = (
        Staff.objects.filter(active=True, roles__internal_code__in=sorted(wanted))
        .order_by("first_name", "last_name")
        .values("id", "first_name", "last_name", "roles__internal_code")
    )

    # dict preserves the query's ordering, so the output stays name-sorted.
    by_staff: dict[str, dict] = {}
    for row in rows:
        staff_id = str(row["id"])
        entry = by_staff.setdefault(
            staff_id,
            {
                "id": staff_id,
                "name": f"{row['first_name']} {row['last_name']}".strip(),
                "roles": set(),
            },
        )
        if row["roles__internal_code"]:
            entry["roles"].add(row["roles__internal_code"])

    providers: list[dict] = []
    rooms: list[dict] = []
    for entry in by_staff.values():
        staff_roles = entry.pop("roles")
        if ROOM_ROLE_CODE in staff_roles:
            rooms.append(entry)
        elif staff_roles & role_list:
            providers.append(entry)
    return providers, rooms
