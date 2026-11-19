"""Who can view and edit whose availability.

The rules, in order:

1. Admins can view and edit every provider and change Settings. Admins are the
   active staff holding a Canvas role picked in Settings, the active people
   picked in Settings, anyone in the ``allowed-staff-keys`` plugin secret, and
   Canvas Support. Canvas Support (the staff key every instance is created with)
   is always an admin, so a practice is never locked out of Settings.
   Until admins are first saved, and with nobody in the secret, every staff
   member is an admin, which is how the plugin behaved before access control
   existed; that is what lets a new practice name its admins. After that it
   fails closed: if no saved admin is active, only the secret and Canvas
   Support are admins. Settings warns when an admin role has no active staff or
   an admin is deactivated, so it rarely comes to that.
2. Every staff member can view their own availability. They can edit it too,
   unless default access is "none".
3. A scheduler in one or more editing groups can edit only the providers in
   those groups. They can view everyone else unless default access is "none".
4. Everyone else gets the default access level: "full" (view and edit every
   provider), "view" (view only), or "none" (view their own and nobody else's,
   with no editing).

Until a default access level is saved, it is "full", except on a practice that
restricted the plugin with the ``allowed-staff-keys`` secret: there it is
"none", so staff the secret left out do not gain access when this ships.
"""

from __future__ import annotations

from typing import Any

from canvas_sdk.v1.data.staff import Staff, StaffRole
from django.db.models import Q

from provider_availability.api._auth import _canonical_id
from provider_availability.engine.models import is_uuid
from provider_availability.engine.settings import get_access_config

# The Canvas Support staff key. Every production instance has it, active, under
# this key (checked across the fleet in 2026-11); on a few the account was renamed,
# so it is matched by key, never by name. It is always an admin: the break-glass.
CANVAS_SUPPORT_KEY = "4150cd20de8a470aa570a852859ac87e"


def _secret_admin_ids(secrets: dict | None) -> set[str]:
    raw = ((secrets or {}).get("allowed-staff-keys", "") or "")
    return {_canonical_id(part) for part in raw.split(",") if part.strip()}


def _valid(ids: list[str] | tuple[str, ...] | str) -> list[str]:
    # A malformed id would raise a ValidationError inside the query, which the
    # sandbox gives no way to catch, so it is screened out here instead.
    return [i for i in ([ids] if isinstance(ids, str) else ids) if i and is_uuid(i)]


def _codes(codes: list[str] | tuple[str, ...]) -> list[str]:
    return sorted({str(c).strip().upper() for c in codes if str(c or "").strip()})


def _role_q(path: str, codes: list[str]) -> Q:
    """Match any of these role internal codes, ignoring case like engine.roles does."""
    match = Q()
    for code in codes:
        match |= Q(**{f"{path}__iexact": code})
    return match


def active_staff_ids(role_codes: list[str] | tuple[str, ...], staff_ids: list[str] | tuple[str, ...] | str = ()) -> set[str]:
    """Canonical ids of the active staff who hold one of these roles or are named directly.

    One query. Unknown codes and malformed ids add nobody, and neither do deactivated staff.
    """
    codes, people = _codes(role_codes), _valid(staff_ids)
    if not codes and not people:
        return set()
    return {_canonical_id(str(sid)) for sid in _query_active_staff(codes, people) if sid}


def _query_active_staff(codes: list[str], people: list[str]) -> list[Any]:
    match = Q()
    if codes:
        match |= _role_q("roles__internal_code", codes)
    if people:
        match |= Q(id__in=people)
    return list(Staff.objects.filter(match, active=True).values_list("id", flat=True).distinct())


def roles_with_active_staff(role_codes: list[str]) -> set[str]:
    """Which of these role internal codes at least one active staff member holds (upper-cased)."""
    codes = _codes(role_codes)
    if not codes:
        return set()
    rows = StaffRole.objects.filter(_role_q("internal_code", codes), staff__active=True).values_list(
        "internal_code", flat=True
    ).distinct()
    return {str(c).strip().upper() for c in rows if c}


def role_names(role_codes: list[str]) -> dict[str, str]:
    """Display names for these role internal codes, including roles no active staff hold now."""
    codes = _codes(role_codes)
    if not codes:
        return {}
    names: dict[str, str] = {}
    for code, name in StaffRole.objects.filter(_role_q("internal_code", codes)).values_list("internal_code", "name"):
        key = str(code or "").strip().upper()
        if key and name and key not in names:
            names[key] = str(name)
    return names


def secret_admin_ids(secrets: dict | None) -> set[str]:
    """Staff listed in the ``allowed-staff-keys`` secret. They are always admins."""
    return _secret_admin_ids(secrets)


def admin_ids(secrets: dict | None, config: dict[str, Any] | None = None) -> set[str]:
    """Staff ids that are admins through Settings or the secret (Canvas Support is added in Access).

    Empty before admins are first saved means everyone is an admin; empty after means
    only Canvas Support is (see ``everyone_is_admin``).
    """
    config = config if config is not None else get_access_config()
    admins = active_staff_ids(config.get("admin_role_codes", []), config.get("admin_staff_ids", []))
    return admins | _secret_admin_ids(secrets)


def everyone_is_admin(admins: set[str], config: dict[str, Any]) -> bool:
    """Only before admins are first saved, and with nobody in the secret."""
    return not admins and not config.get("admins_saved")


def effective_default_access(secrets: dict | None, config: dict[str, Any] | None = None) -> str:
    """The default access level in force, including the unsaved starting value."""
    config = config if config is not None else get_access_config()
    if config.get("default_access_saved"):
        return str(config["default_access"])
    return "none" if _secret_admin_ids(secrets) else "full"


class Access:
    """What one signed-in staff member can do. Build with ``Access.for_staff``."""

    def __init__(
        self,
        staff_id: str,
        is_admin: bool,
        group_providers: set[str] | None,
        default_access: str,
    ) -> None:
        self.staff_id = staff_id
        self.is_admin = is_admin
        # None: not a scheduler in any group. A set (possibly empty): the
        # providers their groups cover, which is all they can edit.
        self.group_providers = group_providers
        self.default_access = default_access

    @classmethod
    def for_staff(cls, staff_id: str, secrets: dict | None) -> "Access":
        config = get_access_config()
        sid = _canonical_id(staff_id)
        admins = admin_ids(secrets, config)
        is_admin = bool(sid) and (sid == CANVAS_SUPPORT_KEY or sid in admins or everyone_is_admin(admins, config))
        group_providers: set[str] | None = None
        for group in config["groups"]:
            if sid and sid in {_canonical_id(s) for s in group["schedulers"]}:
                group_providers = (group_providers or set()) | {_canonical_id(p) for p in group["providers"]}
        return cls(sid, is_admin, group_providers, effective_default_access(secrets, config))

    def can_edit(self, provider_id: str) -> bool:
        pid = _canonical_id(provider_id)
        if not self.staff_id:
            return False
        if self.is_admin:
            return True
        if self.group_providers is not None and pid in self.group_providers:
            return True
        if pid == self.staff_id:
            return self.default_access != "none"
        if self.group_providers is not None:
            return False
        return self.default_access == "full"

    def can_view_others(self) -> bool:
        """Whether this staff member can see providers other than themselves."""
        return bool(self.staff_id) and (
            self.is_admin or bool((self.group_providers or set()) - {self.staff_id}) or self.default_access != "none"
        )

    def can_view(self, provider_id: str) -> bool:
        if self.can_edit(provider_id):
            return True
        if not self.staff_id:
            return False
        return _canonical_id(provider_id) == self.staff_id or self.default_access != "none"

    def can_edit_all(self, provider_ids: list[str] | set[str]) -> bool:
        return all(self.can_edit(p) for p in provider_ids)

    def summary(self) -> dict[str, Any]:
        """What the page needs to show the right buttons. Sent with the page and /access/me."""
        return {
            "staff_id": self.staff_id,
            "is_admin": self.is_admin,
            "in_group": self.group_providers is not None,
            "group_providers": sorted(self.group_providers or []),
            "default_access": self.default_access,
        }
