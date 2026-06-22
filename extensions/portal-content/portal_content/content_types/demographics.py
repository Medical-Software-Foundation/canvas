"""Patient demographics portal content (My Information tab).

Read-only profile data from the SDK data layer, mirroring the MSF
patient-portal-profile reference: name, date of birth, registration email,
addresses, care team, and preferred pharmacy. Queries use select_related /
prefetch_related to avoid N+1. v1 is read-only; updates still go through staff.
"""

from __future__ import annotations

from canvas_sdk.v1.data.care_team import CareTeamMembership, CareTeamMembershipStatus
from canvas_sdk.v1.data.patient import Patient
from logger import log


def get_demographics(patient_id: str) -> dict | None:
    """Return the patient's profile information, or None if the patient is missing."""
    try:
        patient = (
            Patient.objects.select_related("user")
            .prefetch_related("addresses", "photos", "settings")
            .get(id=patient_id)
        )
    except Patient.DoesNotExist:
        log.warning(f"Patient {patient_id} not found for demographics")
        return None

    portal_user = patient.user if patient.user and patient.user.is_portal_registered else None

    return {
        "full_name": patient.preferred_full_name,
        "date_of_birth": patient.birth_date.strftime("%B %d, %Y") if patient.birth_date else None,
        "email": portal_user.email if portal_user else None,
        "photo_url": patient.photo_url,
        "addresses": _addresses(patient),
        "care_team": _care_team(patient_id),
        "preferred_pharmacy": _pharmacy_name(patient),
    }


def _addresses(patient: Patient) -> list[dict]:
    result = []
    for addr in patient.addresses.all():
        result.append(
            {
                "line1": addr.line1,
                "line2": addr.line2,
                "city": addr.city,
                "state": addr.state_code or addr.state,
                "postal_code": addr.postal_code,
            }
        )
    return result


def _care_team(patient_id: str) -> list[dict]:
    members = CareTeamMembership.objects.values(
        "staff__first_name",
        "staff__last_name",
        "staff__prefix",
        "staff__suffix",
        "role_display",
    ).filter(patient__id=patient_id, status=CareTeamMembershipStatus.ACTIVE)

    team = []
    for member in members:
        parts = [
            p
            for p in (member["staff__prefix"], member["staff__first_name"], member["staff__last_name"])
            if p
        ]
        name = " ".join(parts)
        if member["staff__suffix"]:
            name = f"{name}, {member['staff__suffix']}"
        team.append({"name": name, "role": member["role_display"] or ""})
    return team


def _pharmacy_name(patient: Patient) -> str | None:
    """Best-effort pharmacy label; the preferred_pharmacy dict shape varies by writer."""
    pharmacy = patient.preferred_pharmacy
    if isinstance(pharmacy, dict):
        return pharmacy.get("name") or pharmacy.get("pharmacy_name") or pharmacy.get("ncpdp_id")
    return None
