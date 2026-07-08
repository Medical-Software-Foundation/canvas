"""Shared test helpers."""

from __future__ import annotations

from typing import Any

import pytest


class FakeCache:
    """In-memory stand-in for the SDK cache (get/set/delete with the same signatures)."""

    def __init__(self) -> None:
        self.store: dict[str, Any] = {}

    def set(self, key: str, value: Any, timeout_seconds: int | None = None) -> None:
        self.store[key] = value

    def get(self, key: str, default: Any | None = None) -> Any:
        return self.store.get(key, default)

    def delete(self, key: str) -> None:
        self.store.pop(key, None)


@pytest.fixture
def fake_cache() -> FakeCache:
    return FakeCache()
