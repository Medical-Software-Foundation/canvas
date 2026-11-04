"""Which staff members may see a patient's Oura data.

``StaffSessionAuthMixin`` only establishes that the caller is logged-in staff;
per the Canvas SimpleAPI docs it "makes no assertions about the particular
staff member". Deciding which patients a staff member may see is the plugin's
job, so every staff route calls ``staff_can_view`` before touching patient data.

The rule is a practice setting, ``OURA_ACCESS_RULE``:

* ``care_team`` (the default): only active members of the patient's care team.
  Least privilege, so it is what a practice gets unless it chooses otherwise.
* ``practice``: any active staff member, for practices that do not maintain
  care teams or that rely on covering clinicians.

An unrecognized value is a configuration error, reported to staff by name,
and never silently widened.
"""

from typing import Any

from canvas_sdk.v1.data import Patient, Staff
from canvas_sdk.v1.data.care_team import CareTeamMembership, CareTeamMembershipStatus

ACCESS_RULE = "OURA_ACCESS_RULE"
RULE_CARE_TEAM = "care_team"
RULE_PRACTICE = "practice"
RULES: tuple[str, ...] = (RULE_CARE_TEAM, RULE_PRACTICE)
DEFAULT_RULE = RULE_CARE_TEAM

# Set by Canvas from the browser session and stripped from anything a client
# sends, so they identify the caller reliably. This is the same check the SDK's
# own SessionCredentials performs; its exception type is not importable from
# inside the plugin sandbox, so the headers are read here directly.
USER_TYPE_HEADER = "canvas-logged-in-user-type"
USER_ID_HEADER = "canvas-logged-in-user-id"


def resolve_rule(secrets: dict[str, str] | None) -> str | None:
    """The configured rule, the default when unset, or None when unrecognized."""
    raw = ((secrets or {}).get(ACCESS_RULE) or "").strip().lower()
    if not raw:
        return DEFAULT_RULE
    return raw if raw in RULES else None


def logged_in_staff_id(headers: Any) -> str | None:
    """The calling staff member's id, or None if the caller is not staff."""
    if (headers.get(USER_TYPE_HEADER) or "") != "Staff":
        return None
    staff_id = (headers.get(USER_ID_HEADER) or "").strip()
    return staff_id or None


def staff_can_view(staff_id: str, patient_id: str, rule: str) -> bool:
    """Whether this staff member may see this patient under ``rule``.

    Inactive staff never qualify. Under ``practice``, the patient must exist,
    so the routes cannot be used to probe arbitrary ids.
    """
    if not Staff.objects.filter(id=staff_id, active=True).exists():
        return False
    if rule == RULE_PRACTICE:
        return bool(Patient.objects.filter(id=patient_id).exists())
    if rule == RULE_CARE_TEAM:
        return bool(
            CareTeamMembership.objects.filter(
                patient__id=patient_id,
                staff__id=staff_id,
                status=CareTeamMembershipStatus.ACTIVE,
            ).exists()
        )
    return False
