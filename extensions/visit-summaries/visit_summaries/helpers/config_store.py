"""Configuration persistence helper for visit-summaries plugin."""
from __future__ import annotations

import json
from typing import Any

from canvas_sdk.caching.plugins import get_cache
from logger import log


DEFAULT_CONFIG = {
    "enable_previous_visit": True,
    "enable_since_last_visit": True,
    "enable_avs": True,
}

CACHE_KEY = "visit_summaries_config"


def _get_cache() -> Any:
    """Return the plugin cache instance."""
    return get_cache()


def get_config() -> dict:
    """Return current config, falling back to defaults for missing keys."""
    cache = _get_cache()
    raw = cache.get(CACHE_KEY)
    stored = {}
    if raw:
        try:
            stored = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            pass
    return {**DEFAULT_CONFIG, **stored}


def update_config(new_values: dict) -> dict:
    """Merge new_values into the config and persist to cache."""
    current = get_config()
    current.update(new_values)
    cache = _get_cache()
    cache.set(CACHE_KEY, json.dumps(current))
    log.info(f"[visit_summaries] Config updated: {json.dumps(current)}")
    return current


def is_feature_enabled(feature_key: str) -> bool:
    """Check whether a named feature is enabled in the current config."""
    config = get_config()
    return bool(config.get(feature_key, True))
