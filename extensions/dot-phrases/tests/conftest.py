from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import pytest

ADMIN_TEAM = "Dot Phrase Admins"
TEAM_MEMBERS = {"a" * 32, "abc", "def"}


class FakeTeams:
    """Stands in for Team.objects: one team, ADMIN_TEAM, with TEAM_MEMBERS on it."""

    def __init__(self, name: str = "", member: str = "") -> None:
        self.name, self.member = name, member

    def filter(self, name__iexact: str, members__id: str) -> FakeTeams:
        return FakeTeams(name__iexact, members__id)

    def exists(self) -> bool:
        return self.name.lower() == ADMIN_TEAM.lower() and self.member in TEAM_MEMBERS


@pytest.fixture(autouse=True)
def admin_team() -> Iterator[Any]:
    with patch("dot_phrases.library.Team") as team:
        team.objects = FakeTeams()
        yield team
