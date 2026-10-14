from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
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


class MemoryCache:
    """Stands in for the plugin cache in library code."""

    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any, timeout_seconds: int | None = None) -> None:
        self.data[key] = value

    def delete(self, key: str) -> None:
        self.data.pop(key, None)


@pytest.fixture(autouse=True)
def library_cache_and_calendars() -> Iterator[Any]:
    """Library code reads the cache and calendars for time zones; give it an empty cache and no calendars."""
    cache = MemoryCache()
    with patch("dot_phrases.library.get_cache", return_value=cache), patch("dot_phrases.library.Calendar") as calendar:
        calendar.objects.values_list.return_value = []
        yield SimpleNamespace(cache=cache, calendar=calendar)
