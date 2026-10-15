"""Who can view and edit whose availability.

The rules, in order:

1. Admins can view and edit every provider and change Settings. Admins are the
   members of the Canvas team picked in Settings. With no team picked (or a team
   with no members), the ``allowed-staff-keys`` plugin secret lists them. With
   neither, every staff member is an admin, which is how the plugin behaved
   before access control existed.
2. Every staff member can view and edit their own availability.
3. A scheduler in one or more editing groups can edit only the providers in
   those groups. They can view everyone else unless default access is "none".
4. Everyone else gets the default access level: "full" (view and edit every
   provider), "view" (view only), or "none" (only their own).

Until a default access level is saved, it is "full", except on a practice that
restricted the plugin with the ``allowed-staff-keys`` secret: there it is
"none", so staff the secret left out do not gain access when this ships.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from canvas_sdk.v1.data.team import Team
from logger import log

from provider_availability.api._auth import _canonical_id
from provider_availability.engine.settings import get_access_config


def _secret_admin_ids(secrets: dict | None) -> set[str]:
    raw = ((secrets or {}).get("allowed-staff-keys", "") or "")
    return {_canonical_id(part) for part in raw.split(",") if part.strip()}


def team_member_ids(team_id: str) -> set[str]:
    """Canonical staff ids of a Canvas team's members. Empty for an unknown team id."""
    # A malformed id would raise a ValidationError inside the query, which the
    # sandbox gives no way to catch, so it is screened out here instead.
    try:
        UUID(team_id)
    except (ValueError, TypeError, AttributeError):
        return set()
    members = Team.objects.filter(id=team_id).values_list("members__id", flat=True)
    return {_canonical_id(str(m)) for m in members if m}


def admin_ids(secrets: dict | None, config: dict[str, Any] | None = None) -> set[str]:
    """Staff ids that count as admins. Empty means everyone is an admin."""
    config = config if config is not None else get_access_config()
    team_id = config.get("admin_team_id", "")
    if team_id:
        members = team_member_ids(team_id)
        if members:
            return members
        log.warning("access: admin team %s has no members; using the allowed-staff-keys secret", team_id)
    return _secret_admin_ids(secrets)


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
        is_admin = not admins or (bool(sid) and sid in admins)
        group_providers: set[str] | None = None
        for group in config["groups"]:
            if sid and sid in {_canonical_id(s) for s in group["schedulers"]}:
                group_providers = (group_providers or set()) | {_canonical_id(p) for p in group["providers"]}
        return cls(sid, is_admin, group_providers, effective_default_access(secrets, config))

    def can_edit(self, provider_id: str) -> bool:
        pid = _canonical_id(provider_id)
        if not self.staff_id:
            return False
        if self.is_admin or pid == self.staff_id:
            return True
        if self.group_providers is not None:
            return pid in self.group_providers
        return self.default_access == "full"

    def can_view(self, provider_id: str) -> bool:
        if self.can_edit(provider_id):
            return True
        return bool(self.staff_id) and self.default_access != "none"

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
