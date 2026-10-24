"""Who is a favorites admin, and the practice-wide settings.

The admin list lives in the plugin (FavoritesAdmin rows). The FIRST_ADMIN plugin variable names one
login email; while the list is empty, that person counts as an admin and is written to the list the
first time they use an admin route. After that FIRST_ADMIN is not read again.

Canvas's root support login (the "Canvas Support" staff record) is always an admin, so Canvas
support can manage favorites on any instance, including one with no admins left. It is recognized by
its staff key, which is the same on every Canvas instance (checked on all 226 production instances,
2026-10-14). It is never written to the admin list, so it doesn't show in Settings and doesn't count
toward "at least one admin".

Every check fails closed: no staff id, an empty list with an empty or unknown FIRST_ADMIN, or an
inactive staff member means "not an admin".
"""

from __future__ import annotations

from typing import Any

from canvas_sdk.v1.data import Staff

from order_favorites.models import FavoritesAdmin, PracticeSetting

KINDS = ("rx", "lab")
ROOT_STAFF_KEY = "4150cd20de8a470aa570a852859ac87e"
SETTING_DEFAULTS: dict[str, Any] = {"rx_enabled": True, "lab_enabled": True, "set_enabled": True}


def first_admin_email(secrets: dict[str, Any] | None) -> str:
    return str((secrets or {}).get("FIRST_ADMIN") or "").strip().lower()


def staff_dbid(staff_id: str | None) -> int | None:
    """An active staff member's database id from their Staff id, or None."""
    if not staff_id:
        return None
    dbid: int | None = Staff.objects.filter(id=staff_id, active=True).values_list("dbid", flat=True).first()
    return dbid


def _first_admin_dbid(secrets: dict[str, Any] | None) -> int | None:
    email = first_admin_email(secrets)
    if not email:
        return None
    matches = list(Staff.objects.filter(active=True, user__email__iexact=email).values_list("dbid", flat=True)[:2])
    # Two staff records with one login email can't be told apart, so neither is trusted.
    return matches[0] if len(matches) == 1 else None


def listed_admins() -> Any:
    """The practice's admin list. Root is left out even if an older version wrote it there."""
    return FavoritesAdmin.objects.exclude(staff__id=ROOT_STAFF_KEY)


def is_admin(staff_id: str | None, secrets: dict[str, Any] | None) -> bool:
    """Whether this staff member manages practice favorites. Read-only, safe anywhere."""
    me = staff_dbid(staff_id)
    if me is None:
        return False
    if staff_id == ROOT_STAFF_KEY:
        return True
    if listed_admins().exists():
        return bool(listed_admins().filter(staff_id=me, staff__active=True).exists())
    return me == _first_admin_dbid(secrets)


def seed_first_admin(secrets: dict[str, Any] | None) -> None:
    """Write the FIRST_ADMIN person to the admin list, once, if the list is still empty."""
    if listed_admins().exists():
        return
    dbid = _first_admin_dbid(secrets)
    if dbid is not None and dbid != staff_dbid(ROOT_STAFF_KEY):
        FavoritesAdmin.objects.get_or_create(staff_id=dbid)


def get_setting(key: str) -> Any:
    row = PracticeSetting.objects.filter(key=key).first()
    if row is None or row.value is None:
        return SETTING_DEFAULTS.get(key)
    return row.value


def set_setting(key: str, value: Any) -> None:
    PracticeSetting.objects.update_or_create(key=key, defaults={"value": value})


def enabled_kinds() -> list[str]:
    """The order types the practice uses. Never empty: with both switched off, both count as on."""
    kinds = [kind for kind in KINDS if get_setting(f"{kind}_enabled")]
    return kinds or list(KINDS)


def sets_enabled() -> bool:
    """Order sets can be switched off on their own, separately from prescriptions and labs."""
    return bool(get_setting("set_enabled"))


def staff_name(staff: Staff | None) -> str:
    if staff is None:
        return ""
    return f"{staff.first_name or ''} {staff.last_name or ''}".strip()
