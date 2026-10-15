"""Practice-wide settings: feature switches, new rule defaults, and access control.

All three live in the plugin cache next to the rules, under their own keys, and
``storage.refresh_all_ttls`` keeps them alive the same way it keeps the rules.
A missing key means "never changed", so every getter returns the starting value
the practice had before these settings existed.
"""

from __future__ import annotations

import uuid
from typing import Any

from provider_availability.engine.storage import (
    ACCESS_KEY,
    CACHE_TTL_SECONDS,
    FEATURES_KEY,
    RULE_DEFAULTS_KEY,
    _get_cache,
)

# Feature switches. Every feature starts on, which is how the plugin behaved
# before the switches existed.
FEATURES = ("buffers", "lead_time", "holds", "overrides", "provider_timezones")

ACCESS_LEVELS = ("full", "view", "none")
DEFAULT_ACCESS = "full"

_RULE_DEFAULT_FIELDS = ("buffer_pre", "buffer_post", "min_lead_hours")
_MAX_GROUP_NAME = 80


# ── Feature switches ───────────────────────────────────────────────────

def get_features() -> dict[str, bool]:
    """Every feature and whether it is on. Unknown stored keys are dropped."""
    stored = _get_cache().get(FEATURES_KEY) or {}
    return {name: bool(stored.get(name, True)) for name in FEATURES}


def is_feature_on(name: str) -> bool:
    return get_features().get(name, True)


def set_feature(name: str, on: bool) -> dict[str, bool]:
    """Turn one feature on or off. Raises ValueError for an unknown feature."""
    if name not in FEATURES:
        raise ValueError(f"Unknown feature: {name}")
    features = get_features()
    features[name] = bool(on)
    _get_cache().set(FEATURES_KEY, features, timeout_seconds=CACHE_TTL_SECONDS)
    return features


# ── New rule defaults ──────────────────────────────────────────────────

def get_rule_defaults() -> dict[str, int]:
    """The values the Add form pre-fills on a new rule. All start at 0, as the form did."""
    stored = _get_cache().get(RULE_DEFAULTS_KEY) or {}
    return {field: int(stored.get(field, 0) or 0) for field in _RULE_DEFAULT_FIELDS}


def set_rule_defaults(values: dict[str, Any]) -> dict[str, int]:
    """Save the defaults. Raises ValueError for anything that is not a whole number from 0 to 10080."""
    cleaned: dict[str, int] = {}
    for field in _RULE_DEFAULT_FIELDS:
        raw = values.get(field, 0)
        try:
            n = int(raw)
        except (TypeError, ValueError):
            raise ValueError(f"{field} must be a whole number") from None
        if n < 0 or n > 10080:
            raise ValueError(f"{field} must be between 0 and 10080")
        cleaned[field] = n
    _get_cache().set(RULE_DEFAULTS_KEY, cleaned, timeout_seconds=CACHE_TTL_SECONDS)
    return cleaned


# ── Access control ─────────────────────────────────────────────────────

def get_access_config() -> dict[str, Any]:
    """Admin team, default access, and editing groups.

    ``admin_team_id`` is "" when no team is picked; the ``allowed-staff-keys``
    secret then lists the admins (see engine.access).
    """
    stored = _get_cache().get(ACCESS_KEY) or {}
    level = stored.get("default_access", DEFAULT_ACCESS)
    groups = [
        {
            "id": str(g.get("id", "")),
            "name": str(g.get("name", "")),
            "schedulers": [str(s) for s in g.get("schedulers", [])],
            "providers": [str(p) for p in g.get("providers", [])],
        }
        for g in stored.get("groups", [])
        if g.get("id")
    ]
    return {
        "admin_team_id": str(stored.get("admin_team_id", "") or ""),
        "default_access": level if level in ACCESS_LEVELS else DEFAULT_ACCESS,
        # False until someone saves a default access level. engine.access uses it
        # so a practice that restricted access with the secret stays restricted.
        "default_access_saved": stored.get("default_access") in ACCESS_LEVELS,
        "groups": groups,
    }


def _save_access_config(config: dict[str, Any]) -> dict[str, Any]:
    stored = {k: v for k, v in config.items() if k != "default_access_saved"}
    if not config.get("default_access_saved"):
        stored.pop("default_access", None)
    _get_cache().set(ACCESS_KEY, stored, timeout_seconds=CACHE_TTL_SECONDS)
    return get_access_config()


def set_admin_team(team_id: str) -> dict[str, Any]:
    """Pick the admin team. "" clears it, which hands admin back to the plugin secret."""
    config = get_access_config()
    config["admin_team_id"] = (team_id or "").strip()
    return _save_access_config(config)


def set_default_access(level: str) -> dict[str, Any]:
    if level not in ACCESS_LEVELS:
        raise ValueError(f"Default access must be one of: {', '.join(ACCESS_LEVELS)}")
    config = get_access_config()
    config["default_access"] = level
    config["default_access_saved"] = True
    return _save_access_config(config)


def _clean_ids(values: Any) -> list[str]:
    if not isinstance(values, list):
        raise ValueError("schedulers and providers must be lists of staff ids")
    seen: list[str] = []
    for v in values:
        s = str(v).strip()
        if s and s not in seen:
            seen.append(s)
    return seen


def save_group(name: str, schedulers: Any, providers: Any, group_id: str = "") -> dict[str, Any]:
    """Create a group, or replace the one with ``group_id``. Returns the saved group.

    Raises ValueError for a missing name, a name another group already uses,
    or an unknown ``group_id``.
    """
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("Group name is required")
    if len(clean_name) > _MAX_GROUP_NAME:
        raise ValueError(f"Group name must be {_MAX_GROUP_NAME} characters or fewer")
    config = get_access_config()
    groups = config["groups"]
    if any(g["name"].lower() == clean_name.lower() and g["id"] != group_id for g in groups):
        raise ValueError(f"A group named {clean_name} already exists")
    group = {
        "id": group_id or uuid.uuid4().hex,
        "name": clean_name,
        "schedulers": _clean_ids(schedulers),
        "providers": _clean_ids(providers),
    }
    if group_id:
        index = next((i for i, g in enumerate(groups) if g["id"] == group_id), None)
        if index is None:
            raise ValueError("Group not found")
        groups[index] = group
    else:
        groups.append(group)
    _save_access_config(config)
    return group


def delete_group(group_id: str) -> bool:
    config = get_access_config()
    kept = [g for g in config["groups"] if g["id"] != group_id]
    if len(kept) == len(config["groups"]):
        return False
    config["groups"] = kept
    _save_access_config(config)
    return True
