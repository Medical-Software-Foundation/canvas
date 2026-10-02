"""Who gets a failed fax's task when a provider sent it.

A provider's failed fax goes to the patient's care team member in a named role (for
example "Care Coordinator"), so the provider isn't the one chasing it. With no one in that
role, or when the sender isn't a provider, the task goes to the sender as usual. Both
settings must be set for any rerouting.
"""

from dataclasses import dataclass
from typing import Any

from canvas_sdk.v1.data import CareTeamMembership, CareTeamRole, Staff, StaffRole
from logger import log

from failed_fax_dashboard.services.util import chunked

PROVIDER_ROLES_SETTING = "PROVIDER_ROLES"
PROVIDER_TASK_ROLE_SETTING = "PROVIDER_FAX_TASK_ROLE"
ID_CHUNK = 500
ACTIVE = "active"


@dataclass(frozen=True)
class Routing:
    """The two routing settings, cleaned."""

    # Staff role codes, abbreviations, or names, lowercased.
    provider_roles: frozenset[str]
    # The care team role's name as configured (matched ignoring capitals).
    care_team_role: str

    @property
    def on(self) -> bool:
        """Whether provider faxes are rerouted at all."""
        return bool(self.provider_roles and self.care_team_role)


def routing_from(secrets: dict[str, Any]) -> Routing:
    """Read the routing settings. Roles are comma separated; spaces and capitals don't matter."""
    roles = frozenset(
        part.strip().lower() for part in (secrets.get(PROVIDER_ROLES_SETTING) or "").split(",") if part.strip()
    )
    return Routing(roles, (secrets.get(PROVIDER_TASK_ROLE_SETTING) or "").strip())


def warn_if_unknown_role(routing: Routing) -> None:
    """Log once per job run when the care team role matches no role in Canvas."""
    if routing.on and not CareTeamRole.objects.filter(display__iexact=routing.care_team_role).exists():
        log.warning(
            f"{PROVIDER_TASK_ROLE_SETTING} is '{routing.care_team_role}', which matches no care team role. "
            "Provider faxes go to the sender."
        )


def provider_ids(routing: Routing, staff_ids: set[str]) -> set[str]:
    """Which of these staff hold a role named in the provider roles setting."""
    if not routing.on or not staff_ids:
        return set()
    found: set[str] = set()
    for chunk in chunked(sorted(staff_ids), ID_CHUNK):
        for staff_id, code, abbreviation, name in StaffRole.objects.filter(staff__id__in=chunk).values_list(
            "staff__id", "internal_code", "public_abbreviation", "name"
        ):
            if {(code or "").lower(), (abbreviation or "").lower(), (name or "").lower()} & routing.provider_roles:
                found.add(str(staff_id))
    return found


def role_holders(routing: Routing, patient_ids: set[str]) -> dict[str, Staff]:
    """Each patient's active care team member in the configured role, by patient id.

    Canvas allows one active member per role per patient. Members who aren't active staff
    (an outside organization, a deactivated login) are skipped.
    """
    if not routing.on or not patient_ids:
        return {}
    holders: dict[str, Staff] = {}
    for chunk in chunked(sorted(patient_ids), ID_CHUNK):
        memberships = CareTeamMembership.objects.filter(
            patient__id__in=chunk,
            status=ACTIVE,
            role__display__iexact=routing.care_team_role,
            staff__isnull=False,
            staff__active=True,
        ).select_related("patient", "staff")
        for membership in memberships:
            holders[str(membership.patient.id)] = membership.staff
    return holders


def routed_holder(
    sender_id: str, patient_id: str | None, providers: set[str], holders: dict[str, Staff]
) -> Staff | None:
    """The care team member who gets a provider's failed fax instead of the provider, or None."""
    if sender_id not in providers or not patient_id:
        return None
    holder = holders.get(patient_id)
    if holder is None or str(holder.id) == sender_id:
        return None
    return holder
