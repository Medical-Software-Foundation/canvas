"""Who may curate the resource library.

Authentication and authorization are separate layers and this module is only the
second one. ``StaffSessionAuthMixin`` has already proven there is a live staff
session by the time anything here runs; it says nothing about whether that person
may edit a shared library.
"""

from typing import Any

from canvas_sdk.v1.data.staff import StaffRole
from logger import log

from patient_resources.services.config import PatientResourcesConfig
from patient_resources.services.identity import id_candidates


def is_library_admin(staff: Any, config: PatientResourcesConfig) -> bool:
    """True if this staff member may create, edit, archive or retract resources.

    Fails closed in every branch. The repo has a live disagreement about this --
    ``patient-tags`` and ``dea-prescriber-filter`` both treat an empty
    configuration as "everyone allowed", the second one deliberately, because
    failing closed shipped an admin UI nobody could open. Defaulting to *role
    domains* rather than staff ids sidesteps that trade-off: ``StaffRole.domain``
    is a closed three-value vocabulary that means the same thing on every
    instance, so a shipped default of "administrative roles" is both restrictive
    and immediately usable on a fresh install.
    """
    if staff is None:
        return False

    if config.admin_staff_ids:
        # An explicit allowlist replaces the role rule rather than adding to it.
        # A practice that names three people means those three, not those three
        # plus everyone holding an administrative role.
        allowed = {candidate for value in config.admin_staff_ids for candidate in id_candidates(value)}
        return bool(id_candidates(str(getattr(staff, "id", "") or "")) & allowed)

    if not config.admin_role_domains:
        log.warning("No admin role domains configured; denying library curation")
        return False

    staff_dbid = getattr(staff, "dbid", None)
    if staff_dbid is None:
        return False

    return StaffRole.objects.filter(
        staff__dbid=staff_dbid,
        domain__in=list(config.admin_role_domains),
    ).exists()
