from typing import Any

import pytest


class FakeCache:
    """In-memory stand-in for the plugin cache (get/set/get_many/delete)."""

    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.timeouts: dict[str, int | None] = {}

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any, timeout_seconds: int | None = None) -> None:
        self.data[key] = value
        self.timeouts[key] = timeout_seconds

    def get_or_set(
        self, key: str, default: Any = None, timeout_seconds: int | None = None
    ) -> Any:
        if key not in self.data:
            self.set(key, default, timeout_seconds)
        return self.data[key]

    def get_many(self, keys: list[str]) -> dict[str, Any]:
        return {k: self.data[k] for k in keys if k in self.data}

    def delete(self, key: str) -> None:
        self.data.pop(key, None)


@pytest.fixture
def cache() -> FakeCache:
    return FakeCache()
