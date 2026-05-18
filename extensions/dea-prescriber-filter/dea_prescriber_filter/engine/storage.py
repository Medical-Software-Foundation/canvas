"""Cache-based storage for prescriber delegation mappings."""

from __future__ import annotations

from typing import Any

from canvas_sdk.caching.plugins import get_cache

DELEGATIONS_INDEX_KEY = "dea:delegations:index"
DELEGATION_PREFIX = "dea:delegation:"
CACHE_TTL_SECONDS = 14 * 24 * 60 * 60 - 3600  # 14 days minus 1 hour buffer


def _get_cache() -> Any:
    return get_cache()


def get_all_delegations() -> dict[str, list[str]]:
    """Return all delegations as {provider_key: [staff_key, ...]}."""
    cache = _get_cache()
    index = cache.get(DELEGATIONS_INDEX_KEY)
    if not index:
        return {}

    result = {}
    for provider_key in index:
        data = cache.get(f"{DELEGATION_PREFIX}{provider_key}")
        if data and isinstance(data, list):
            result[provider_key] = data
    return result


def set_delegation(provider_key: str, staff_keys: list[str]) -> None:
    """Set the authorized staff list for a provider."""
    cache = _get_cache()

    if staff_keys:
        cache.set(
            f"{DELEGATION_PREFIX}{provider_key}",
            staff_keys,
            timeout_seconds=CACHE_TTL_SECONDS,
        )
        # Update index, always refreshing its TTL so the index can't expire
        # before the per-provider entries on a stable deployment.
        index = cache.get(DELEGATIONS_INDEX_KEY) or []
        if provider_key not in index:
            index.append(provider_key)
        cache.set(DELEGATIONS_INDEX_KEY, index, timeout_seconds=CACHE_TTL_SECONDS)
    else:
        remove_delegation(provider_key)


def remove_delegation(provider_key: str) -> None:
    """Remove all delegations for a provider."""
    cache = _get_cache()
    cache.delete(f"{DELEGATION_PREFIX}{provider_key}")

    index = cache.get(DELEGATIONS_INDEX_KEY) or []
    if provider_key in index:
        index.remove(provider_key)
        cache.set(DELEGATIONS_INDEX_KEY, index, timeout_seconds=CACHE_TTL_SECONDS)
