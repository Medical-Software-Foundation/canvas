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

# Feature switches. The original five start on, which is how the plugin behaved
# before the switches existed. Facility rounds and facility blocks are new, so they
# start off: a practice that upgrades sees no change until an admin turns them on.
FEATURES = ("buffers", "lead_time", "holds", "overrides", "provider_timezones", "facility_rounds", "facility_blocks")
_STARTS_OFF = ("facility_rounds", "facility_blocks")

ACCESS_LEVELS = ("full", "view", "none")
DEFAULT_ACCESS = "full"

_RULE_DEFAULT_FIELDS = ("buffer_pre", "buffer_post", "min_lead_hours")
_MAX_GROUP_NAME = 80


# ── Feature switches ───────────────────────────────────────────────────

def get_features() -> dict[str, bool]:
    """Every feature and whether it is on. Unknown stored keys are dropped."""
    stored = _get_cache().get(FEATURES_KEY) or {}
    return {name: bool(stored.get(name, name not in _STARTS_OFF)) for name in FEATURES}


def is_feature_on(name: str) -> bool:
    return get_features().get(name, name not in _STARTS_OFF)


# Stored next to the switches: whether date overrides saved before the switch
# was turned off keep applying. Only read while overrides are off.
_KEEP_OVERRIDES = "overrides_keep_existing"


def set_feature(name: str, on: bool, keep_existing_overrides: bool = True) -> dict[str, bool]:
    """Turn one feature on or off. Raises ValueError for an unknown feature."""
    if name not in FEATURES:
        raise ValueError(f"Unknown feature: {name}")
    stored = dict(_get_cache().get(FEATURES_KEY) or {})
    stored.update(get_features())
    stored[name] = bool(on)
    if name == "overrides":
        stored[_KEEP_OVERRIDES] = bool(on) or bool(keep_existing_overrides)
    if name == "facility_rounds":
        # keep_existing_overrides doubles as "keep existing rounds" for this switch.
        stored[_KEEP_ROUNDS] = bool(on) or bool(keep_existing_overrides)
    _get_cache().set(FEATURES_KEY, stored, timeout_seconds=CACHE_TTL_SECONDS)
    return get_features()


_KEEP_ROUNDS = "facility_rounds_keep_existing"


def rounds_drawn() -> bool:
    """Whether saved facility rounds are on calendars.

    True while the feature is on. With it off, true only if the admin chose to
    keep the rounds that already existed when the switch was turned off.
    """
    stored = _get_cache().get(FEATURES_KEY) or {}
    if stored.get("facility_rounds", False):
        return True
    return bool(stored.get(_KEEP_ROUNDS, False))


def overrides_applied() -> bool:
    """Whether saved date overrides change providers' hours.

    True while the feature is on. With it off, true only if the admin chose to
    keep applying the overrides that already existed.
    """
    stored = _get_cache().get(FEATURES_KEY) or {}
    if stored.get("overrides", True):
        return True
    return bool(stored.get(_KEEP_OVERRIDES, True))


def applied_overrides(rule: Any) -> list:
    """The rule's date overrides that should change its hours right now."""
    return list(rule.date_overrides) if overrides_applied() else []


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
    """Admin roles and people, default access, and editing groups.

    Admins are the active staff holding a role in ``admin_role_codes`` (StaffRole
    internal codes) plus the active staff in ``admin_staff_ids``; the
    ``allowed-staff-keys`` secret and Canvas Support add more (see engine.access).
    ``admins_saved`` is true once admins have been saved: from then on an empty
    admin set means nobody but Canvas Support, not everyone.
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
    staff_ids = [str(s) for s in stored.get("admin_staff_ids", []) if s]
    role_codes = [_role_code(c) for c in stored.get("admin_role_codes", []) if _role_code(c)]
    saved = bool(stored.get("admins_saved") or staff_ids or role_codes)
    return {
        "admin_role_codes": role_codes,
        "admin_staff_ids": staff_ids,
        "admins_saved": saved,
        "default_access": level if level in ACCESS_LEVELS else DEFAULT_ACCESS,
        # False until someone saves a default access level. engine.access uses it
        # so a practice that restricted access with the secret stays restricted.
        "default_access_saved": stored.get("default_access") in ACCESS_LEVELS,
        "groups": groups,
    }


def _role_code(code: Any) -> str:
    """Role internal codes compare case-insensitively, as in engine.roles."""
    return str(code or "").strip().upper()


def _save_access_config(config: dict[str, Any]) -> dict[str, Any]:
    stored = {k: v for k, v in config.items() if k != "default_access_saved"}
    if not config.get("default_access_saved"):
        stored.pop("default_access", None)
    _get_cache().set(ACCESS_KEY, stored, timeout_seconds=CACHE_TTL_SECONDS)
    return get_access_config()


def set_admins(role_codes: Any, staff_ids: Any) -> dict[str, Any]:
    """Replace the admin roles and admin people, and mark admins as set up."""
    if not isinstance(role_codes, list):
        raise ValueError("admin_role_codes must be a list")
    config = get_access_config()
    config["admin_role_codes"] = sorted({_role_code(c) for c in role_codes if _role_code(c)})
    config["admin_staff_ids"] = _clean_ids(staff_ids)
    config["admins_saved"] = True
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
