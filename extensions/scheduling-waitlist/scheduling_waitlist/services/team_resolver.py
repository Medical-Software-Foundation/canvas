"""Turning the configured scheduling team into an identifier."""

from __future__ import annotations

import uuid

from canvas_sdk.v1.data import Team


def resolve_team_id(configured: str) -> str:
    """Find the team that should receive slot-opened tasks.

    Accepts a team identifier in either dashed or bare form, or the team's
    exact name, because an administrator filling in a secret is far more likely
    to have the name to hand than an identifier.

    Returns an empty string when nothing matches. Callers must then decline to
    raise the task: a task with no team is a task nobody sees, so guessing at a
    fallback would quietly drop the very notification this plugin exists to
    deliver.
    """
    value = (configured or "").strip()
    if not value:
        return ""

    candidates = {value, value.replace("-", "")}
    try:
        candidates.add(str(uuid.UUID(value)))
    except ValueError:
        pass

    team = Team.objects.filter(id__in=candidates).first()
    if team is not None:
        return str(team.id)

    team = Team.objects.filter(name=value).first()
    return str(team.id) if team is not None else ""
