"""Cache-based storage for provider availability rules and admin blocks."""

from __future__ import annotations

import json
from typing import Any

from canvas_sdk.caching.plugins import get_cache
from logger import log

from provider_availability.engine.models import AdminBlock, ProviderAvailabilityRule, RecurringBlock

INDEX_KEY = "pa:rules:index"
BLOCK_INDEX_KEY = "pa:blocks:index"
RECURRING_BLOCK_INDEX_KEY = "pa:recurring_blocks:index"
EVENT_IDS_PREFIX = "pa:event_ids:"
PRACTICE_TZ_KEY = "pa:practice_timezone"
PROVIDER_TZ_PREFIX = "pa:provider_tz:"
PROVIDER_TZ_INDEX_KEY = "pa:provider_tz:index"
INSTALL_SENTINEL_KEY = "pa:installed"
LAST_TTL_REFRESH_KEY = "pa:last_ttl_refresh"
CACHE_TTL_SECONDS = 14 * 24 * 60 * 60 - 3600  # 14 days minus 1 hour buffer
TTL_REFRESH_INTERVAL_SECONDS = 6 * 60 * 60  # 6 hours between full TTL refreshes


def _get_cache() -> Any:
    return get_cache()


# ── Rule CRUD ──────────────────────────────────────────────────────────


def save_rule(rule: ProviderAvailabilityRule) -> None:
    """Save a rule to cache and update the index."""
    cache = _get_cache()
    cache.set(rule.cache_key, rule.to_dict(), timeout_seconds=CACHE_TTL_SECONDS)
    _add_to_index(rule.cache_key)


def get_rule_by_id(provider_id: str, rule_id: str) -> ProviderAvailabilityRule | None:
    """Get a specific rule by provider ID and rule UUID."""
    cache = _get_cache()
    key = f"pa:rules:{provider_id}:{rule_id}"
    data = cache.get(key)
    if data is None:
        return None
    return ProviderAvailabilityRule.from_dict(data)


def get_rules_for_provider(provider_id: str) -> list[ProviderAvailabilityRule]:
    """Get all rules for a specific provider."""
    all_keys = _get_index()
    prefix = f"pa:rules:{provider_id}:"
    provider_keys = [k for k in all_keys if k.startswith(prefix)]

    if not provider_keys:
        return []

    cache = _get_cache()
    data_map = cache.get_many(provider_keys)
    rules = []
    for data in data_map.values():
        if data is not None:
            rules.append(ProviderAvailabilityRule.from_dict(data))
    return rules


def get_all_rules() -> list[ProviderAvailabilityRule]:
    """Get all rules from cache."""
    all_keys = _get_index()
    if not all_keys:
        return []

    cache = _get_cache()
    data_map = cache.get_many(all_keys)
    rules = []
    for data in data_map.values():
        if data is not None:
            rules.append(ProviderAvailabilityRule.from_dict(data))
    return rules


def delete_rule_by_id(provider_id: str, rule_id: str) -> bool:
    """Delete a specific rule by provider ID and rule UUID."""
    cache = _get_cache()
    key = f"pa:rules:{provider_id}:{rule_id}"
    cache.delete(key)
    _remove_from_index(key)
    return True


def delete_rules_for_provider(provider_id: str) -> int:
    """Delete all rules for a provider. Returns count of deleted rules."""
    all_keys = _get_index()
    prefix = f"pa:rules:{provider_id}:"
    provider_keys = [k for k in all_keys if k.startswith(prefix)]

    cache = _get_cache()
    for key in provider_keys:
        cache.delete(key)
        _remove_from_index(key)

    return len(provider_keys)


# ── Rule index helpers ─────────────────────────────────────────────────


def _get_index() -> list[str]:
    """Get the list of all rule cache keys."""
    cache = _get_cache()
    index = cache.get(INDEX_KEY)
    if index is None:
        return []
    return list(index)


def _add_to_index(key: str) -> None:
    """Add a key to the rule index."""
    cache = _get_cache()
    index = _get_index()
    if key not in index:
        index.append(key)
    cache.set(INDEX_KEY, index, timeout_seconds=CACHE_TTL_SECONDS)


def _remove_from_index(key: str) -> None:
    """Remove a key from the rule index."""
    cache = _get_cache()
    index = _get_index()
    if key in index:
        index.remove(key)
        cache.set(INDEX_KEY, index, timeout_seconds=CACHE_TTL_SECONDS)


# ── Event ID mapping (rule → Canvas Event UUIDs) ─────────────────────


def save_event_ids(rule_id: str, event_ids: list[str]) -> None:
    """Save the list of Canvas Event UUIDs created for a rule."""
    cache = _get_cache()
    cache.set(f"{EVENT_IDS_PREFIX}{rule_id}", event_ids, timeout_seconds=CACHE_TTL_SECONDS)


def get_event_ids(rule_id: str) -> list[str]:
    """Get stored Canvas Event UUIDs for a rule."""
    cache = _get_cache()
    data = cache.get(f"{EVENT_IDS_PREFIX}{rule_id}")
    return list(data) if data else []


def delete_event_ids(rule_id: str) -> None:
    """Remove stored Canvas Event UUIDs for a rule."""
    cache = _get_cache()
    cache.delete(f"{EVENT_IDS_PREFIX}{rule_id}")


# ── Admin Block CRUD ───────────────────────────────────────────────────


def save_block(block: AdminBlock) -> None:
    """Save an admin block to cache and update the block index."""
    cache = _get_cache()
    cache.set(block.cache_key, block.to_dict(), timeout_seconds=CACHE_TTL_SECONDS)
    _add_to_block_index(block.cache_key)


def get_blocks_for_provider(provider_id: str) -> list[AdminBlock]:
    """Get all admin blocks for a specific provider."""
    all_keys = _get_block_index()
    prefix = f"pa:blocks:{provider_id}:"
    provider_keys = [k for k in all_keys if k.startswith(prefix)]

    if not provider_keys:
        return []

    cache = _get_cache()
    data_map = cache.get_many(provider_keys)
    blocks = []
    for data in data_map.values():
        if data is not None:
            blocks.append(AdminBlock.from_dict(data))
    return blocks


def get_block_by_id(provider_id: str, block_id: str) -> AdminBlock | None:
    """Get a specific block by provider ID and block UUID."""
    cache = _get_cache()
    key = f"pa:blocks:{provider_id}:{block_id}"
    data = cache.get(key)
    if data is None:
        return None
    return AdminBlock.from_dict(data)


def get_all_blocks() -> list[AdminBlock]:
    """Get all admin blocks from cache."""
    all_keys = _get_block_index()
    if not all_keys:
        return []

    cache = _get_cache()
    data_map = cache.get_many(all_keys)
    blocks = []
    for data in data_map.values():
        if data is not None:
            blocks.append(AdminBlock.from_dict(data))
    return blocks


def delete_block(provider_id: str, block_id: str) -> bool:
    """Delete a specific admin block from cache."""
    cache = _get_cache()
    key = f"pa:blocks:{provider_id}:{block_id}"
    cache.delete(key)
    _remove_from_block_index(key)
    return True


# ── Block index helpers ────────────────────────────────────────────────


def _get_block_index() -> list[str]:
    """Get the list of all block cache keys."""
    cache = _get_cache()
    index = cache.get(BLOCK_INDEX_KEY)
    if index is None:
        return []
    return list(index)


def _add_to_block_index(key: str) -> None:
    """Add a key to the block index."""
    cache = _get_cache()
    index = _get_block_index()
    if key not in index:
        index.append(key)
    cache.set(BLOCK_INDEX_KEY, index, timeout_seconds=CACHE_TTL_SECONDS)


def _remove_from_block_index(key: str) -> None:
    """Remove a key from the block index."""
    cache = _get_cache()
    index = _get_block_index()
    if key in index:
        index.remove(key)
        cache.set(BLOCK_INDEX_KEY, index, timeout_seconds=CACHE_TTL_SECONDS)


# ── Recurring Block CRUD ───────────────────────────────────────────────


def save_recurring_block(block: RecurringBlock) -> None:
    """Save a recurring block to cache and update the index."""
    cache = _get_cache()
    cache.set(block.cache_key, block.to_dict(), timeout_seconds=CACHE_TTL_SECONDS)
    _add_to_recurring_block_index(block.cache_key)


def get_recurring_blocks_for_provider(provider_id: str) -> list[RecurringBlock]:
    """Get all recurring blocks for a specific provider."""
    all_keys = _get_recurring_block_index()
    prefix = f"pa:recurring_blocks:{provider_id}:"
    provider_keys = [k for k in all_keys if k.startswith(prefix)]

    if not provider_keys:
        return []

    cache = _get_cache()
    data_map = cache.get_many(provider_keys)
    blocks = []
    for data in data_map.values():
        if data is not None:
            blocks.append(RecurringBlock.from_dict(data))
    return blocks


def get_all_recurring_blocks() -> list[RecurringBlock]:
    """Get all recurring blocks from cache."""
    all_keys = _get_recurring_block_index()
    if not all_keys:
        return []

    cache = _get_cache()
    data_map = cache.get_many(all_keys)
    blocks = []
    for data in data_map.values():
        if data is not None:
            blocks.append(RecurringBlock.from_dict(data))
    return blocks


def get_recurring_block_by_id(provider_id: str, block_id: str) -> RecurringBlock | None:
    """Get a specific recurring block by provider ID and block UUID."""
    cache = _get_cache()
    key = f"pa:recurring_blocks:{provider_id}:{block_id}"
    data = cache.get(key)
    if data is None:
        return None
    return RecurringBlock.from_dict(data)


def delete_recurring_block(provider_id: str, block_id: str) -> bool:
    """Delete a specific recurring block from cache."""
    cache = _get_cache()
    key = f"pa:recurring_blocks:{provider_id}:{block_id}"
    cache.delete(key)
    _remove_from_recurring_block_index(key)
    return True


# ── Recurring block index helpers ─────────────────────────────────────


def _get_recurring_block_index() -> list[str]:
    """Get the list of all recurring block cache keys."""
    cache = _get_cache()
    index = cache.get(RECURRING_BLOCK_INDEX_KEY)
    if index is None:
        return []
    return list(index)


def _add_to_recurring_block_index(key: str) -> None:
    """Add a key to the recurring block index."""
    cache = _get_cache()
    index = _get_recurring_block_index()
    if key not in index:
        index.append(key)
    cache.set(RECURRING_BLOCK_INDEX_KEY, index, timeout_seconds=CACHE_TTL_SECONDS)


def _remove_from_recurring_block_index(key: str) -> None:
    """Remove a key from the recurring block index."""
    cache = _get_cache()
    index = _get_recurring_block_index()
    if key in index:
        index.remove(key)
        cache.set(RECURRING_BLOCK_INDEX_KEY, index, timeout_seconds=CACHE_TTL_SECONDS)


# ── Group lookups ──────────────────────────────────────────────────────


def get_rules_by_group(group_id: str) -> list[ProviderAvailabilityRule]:
    """Get all rules sharing a group_id."""
    return [r for r in get_all_rules() if r.group_id == group_id]


def get_blocks_by_group(group_id: str) -> list[AdminBlock]:
    """Get all admin blocks sharing a group_id."""
    return [b for b in get_all_blocks() if b.group_id == group_id]


def get_recurring_blocks_by_group(group_id: str) -> list[RecurringBlock]:
    """Get all recurring blocks sharing a group_id."""
    return [b for b in get_all_recurring_blocks() if b.group_id == group_id]


# ── Daily sync date ────────────────────────────────────────────────────

LAST_SYNC_KEY = "pa:last_sync_date"


def get_last_sync_date() -> str:
    """Get the last daily sync date string (ISO format), or empty if never synced."""
    cache = _get_cache()
    val = cache.get(LAST_SYNC_KEY)
    return str(val) if val else ""


def set_last_sync_date(date_str: str) -> None:
    """Store today's date as the last sync date."""
    cache = _get_cache()
    cache.set(LAST_SYNC_KEY, date_str, timeout_seconds=CACHE_TTL_SECONDS)


# ── TTL refresh ────────────────────────────────────────────────────────


def should_refresh_ttls() -> bool:
    """Return True if enough time has elapsed since the last full TTL refresh."""
    cache = _get_cache()
    last = cache.get(LAST_TTL_REFRESH_KEY)
    if last is None:
        return True
    try:
        elapsed = _now_timestamp() - float(last)
        return elapsed >= TTL_REFRESH_INTERVAL_SECONDS
    except (ValueError, TypeError):
        return True


def mark_ttl_refresh_done() -> None:
    """Record that a full TTL refresh just completed."""
    cache = _get_cache()
    cache.set(LAST_TTL_REFRESH_KEY, str(_now_timestamp()), timeout_seconds=CACHE_TTL_SECONDS)


def _now_timestamp() -> float:
    """Current UTC time as a POSIX timestamp."""
    from datetime import UTC, datetime

    return datetime.now(UTC).timestamp()


def refresh_all_ttls() -> int:
    """Refresh TTLs on all cached rules and blocks. Returns count of refreshed rules."""
    cache = _get_cache()

    # Refresh rules (use individual get() calls — get_many returns prefixed keys)
    all_keys = _get_index()
    refreshed = 0
    if all_keys:
        stale_keys = []
        for key in all_keys:
            data = cache.get(key)
            if data is not None:
                cache.set(key, data, timeout_seconds=CACHE_TTL_SECONDS)
                refreshed += 1
            else:
                stale_keys.append(key)

        for key in stale_keys:
            _remove_from_index(key)

        current_index = _get_index()
        if current_index:
            cache.set(INDEX_KEY, current_index, timeout_seconds=CACHE_TTL_SECONDS)

    # Refresh event_id mappings for all active rules
    for key in all_keys:
        parts = key.split(":")
        if len(parts) == 4:
            rule_id = parts[3]
            eid_key = f"{EVENT_IDS_PREFIX}{rule_id}"
            eid_data = cache.get(eid_key)
            if eid_data is not None:
                cache.set(eid_key, eid_data, timeout_seconds=CACHE_TTL_SECONDS)

    # Refresh blocks
    block_keys = _get_block_index()
    if block_keys:
        stale_block_keys = []
        for key in block_keys:
            data = cache.get(key)
            if data is not None:
                cache.set(key, data, timeout_seconds=CACHE_TTL_SECONDS)
            else:
                stale_block_keys.append(key)

        for key in stale_block_keys:
            _remove_from_block_index(key)

        current_block_index = _get_block_index()
        if current_block_index:
            cache.set(BLOCK_INDEX_KEY, current_block_index, timeout_seconds=CACHE_TTL_SECONDS)

    # Refresh recurring blocks
    recurring_keys = _get_recurring_block_index()
    if recurring_keys:
        stale_recurring_keys = []
        for key in recurring_keys:
            data = cache.get(key)
            if data is not None:
                cache.set(key, data, timeout_seconds=CACHE_TTL_SECONDS)
            else:
                stale_recurring_keys.append(key)

        for key in stale_recurring_keys:
            _remove_from_recurring_block_index(key)

        current_recurring_index = _get_recurring_block_index()
        if current_recurring_index:
            cache.set(RECURRING_BLOCK_INDEX_KEY, current_recurring_index, timeout_seconds=CACHE_TTL_SECONDS)

    # Refresh practice timezone
    tz_val = cache.get(PRACTICE_TZ_KEY)
    if tz_val is not None:
        cache.set(PRACTICE_TZ_KEY, tz_val, timeout_seconds=CACHE_TTL_SECONDS)

    # Refresh provider timezones
    tz_index = _get_provider_tz_index()
    if tz_index:
        for pid in tz_index:
            tz_key = f"{PROVIDER_TZ_PREFIX}{pid}"
            tz_data = cache.get(tz_key)
            if tz_data is not None:
                cache.set(tz_key, tz_data, timeout_seconds=CACHE_TTL_SECONDS)
        cache.set(PROVIDER_TZ_INDEX_KEY, tz_index, timeout_seconds=CACHE_TTL_SECONDS)

    # Refresh install sentinel
    sentinel = cache.get(INSTALL_SENTINEL_KEY)
    if sentinel is not None:
        cache.set(INSTALL_SENTINEL_KEY, sentinel, timeout_seconds=CACHE_TTL_SECONDS)

    # Mark that we just completed a full refresh
    mark_ttl_refresh_done()

    return refreshed


# ── Practice timezone ─────────────────────────────────────────────────


def get_practice_timezone() -> str:
    """Get the practice timezone name, defaulting to UTC."""
    cache = _get_cache()
    val = cache.get(PRACTICE_TZ_KEY)
    return str(val) if val else "UTC"


def set_practice_timezone(tz_name: str) -> None:
    """Store the practice timezone name."""
    cache = _get_cache()
    cache.set(PRACTICE_TZ_KEY, tz_name, timeout_seconds=CACHE_TTL_SECONDS)


# ── Per-provider timezone ────────────────────────────────────────────


def get_provider_timezone(provider_id: str) -> str | None:
    """Get a provider's timezone, or None if not explicitly set."""
    cache = _get_cache()
    val = cache.get(f"{PROVIDER_TZ_PREFIX}{provider_id}")
    return str(val) if val else None


def set_provider_timezone(provider_id: str, tz_name: str) -> None:
    """Store a provider's timezone and update the provider TZ index."""
    cache = _get_cache()
    cache.set(f"{PROVIDER_TZ_PREFIX}{provider_id}", tz_name, timeout_seconds=CACHE_TTL_SECONDS)
    _add_to_provider_tz_index(provider_id)


def clear_provider_timezone(provider_id: str) -> None:
    """Remove a provider's explicit timezone (reverts to practice TZ)."""
    cache = _get_cache()
    cache.delete(f"{PROVIDER_TZ_PREFIX}{provider_id}")
    _remove_from_provider_tz_index(provider_id)


def get_all_provider_timezones() -> dict[str, str]:
    """Return a dict of {provider_id: timezone} for all providers with explicit TZ."""
    cache = _get_cache()
    index = _get_provider_tz_index()
    if not index:
        return {}
    result: dict[str, str] = {}
    for pid in index:
        val = cache.get(f"{PROVIDER_TZ_PREFIX}{pid}")
        if val:
            result[pid] = str(val)
    return result


def _get_provider_tz_index() -> list[str]:
    """Get the list of provider IDs with explicit timezone set."""
    cache = _get_cache()
    index = cache.get(PROVIDER_TZ_INDEX_KEY)
    if index is None:
        return []
    return list(index)


def _add_to_provider_tz_index(provider_id: str) -> None:
    """Add a provider ID to the provider TZ index."""
    cache = _get_cache()
    index = _get_provider_tz_index()
    if provider_id not in index:
        index.append(provider_id)
    cache.set(PROVIDER_TZ_INDEX_KEY, index, timeout_seconds=CACHE_TTL_SECONDS)


def _remove_from_provider_tz_index(provider_id: str) -> None:
    """Remove a provider ID from the provider TZ index."""
    cache = _get_cache()
    index = _get_provider_tz_index()
    if provider_id in index:
        index.remove(provider_id)
        cache.set(PROVIDER_TZ_INDEX_KEY, index, timeout_seconds=CACHE_TTL_SECONDS)


# ── Install sentinel ──────────────────────────────────────────────────


def is_first_install() -> bool:
    """Return True if the plugin has never been installed before."""
    cache = _get_cache()
    return cache.get(INSTALL_SENTINEL_KEY) is None


def mark_installed() -> None:
    """Record that the plugin has been installed."""
    cache = _get_cache()
    cache.set(INSTALL_SENTINEL_KEY, "1", timeout_seconds=CACHE_TTL_SECONDS)
