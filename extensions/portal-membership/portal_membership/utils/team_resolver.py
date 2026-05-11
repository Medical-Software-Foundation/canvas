"""Resolve a ``STAFF_OFFBOARDING_TEAM_ID`` secret value to a Team UUID.

The secret can be configured as a hyphenated UUID, a bare-hex UUID, or a
team name. ``resolve_team_id`` covers all three forms, returning ``""``
(and logging) when the value doesn't match any team.
"""
from canvas_sdk.v1.data.team import Team
from logger import log


def resolve_team_id(raw_id: str) -> str:
    """Validate a team ID/name against the database, returning a UUID string.

    Tries hyphenated UUID, bare-hex UUID, then case-insensitive name lookup.
    Returns ``""`` when none match (caller falls back to creating the task
    without a team assignment).
    """
    if not raw_id:
        return ""

    if Team.objects.filter(id=raw_id).exists():
        return raw_id

    alt_id = raw_id.replace("-", "")
    if alt_id != raw_id and Team.objects.filter(id=alt_id).exists():
        return alt_id

    team_by_name = Team.objects.filter(name__iexact=raw_id).first()
    if team_by_name:
        resolved = str(team_by_name.id)
        log.info(f"portal_membership: resolved team name {raw_id!r} to ID {resolved}")
        return resolved

    log.warning(
        f"portal_membership: STAFF_OFFBOARDING_TEAM_ID={raw_id} "
        "not found by ID or name, creating task without team assignment"
    )
    return ""
