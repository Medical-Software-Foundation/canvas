"""Work out who a locked note goes to.

Each recipient type is resolved with a fixed number of queries, however many
rules or care team members there are:

- ``care_team_role``: one query for the patient's active external care team
  members with any of the configured role codes, plus one query for all of
  their directory records. The SDK's ``membership.service_provider`` property
  runs a query per member, so it is deliberately not used here.
- ``facility``: one query for the patient's current facility address.
- ``fixed``: no queries.

A recipient that can't be faxed (no fax number on file, an inactive record)
comes back with ``problem`` set so the caller can log it instead of silently
dropping it.
"""

from dataclasses import dataclass
from datetime import date

from canvas_sdk.v1.data import (
    CareTeamMembership,
    PatientFacilityAddress,
    ServiceProvider,
)
from canvas_sdk.v1.data.care_team import CareTeamMembershipStatus
from canvas_sdk.v1.data.common import AddressState
from canvas_sdk.v1.data.organizational_entity import OrganizationalEntity
from django.db.models import Q

from auto_fax.services.config import (
    RECIPIENT_CARE_TEAM_ROLE,
    RECIPIENT_FACILITY,
    RECIPIENT_FIXED,
    Rule,
)
from auto_fax.services.fax_number import ten_digits


@dataclass(frozen=True)
class Recipient:
    """One fax destination produced by one rule."""

    rule: Rule
    kind: str
    name: str
    fax_digits: str | None
    problem: str | None = None


def _provider_name(provider: ServiceProvider) -> str:
    person = " ".join(
        part for part in (provider.first_name, provider.last_name) if part
    ).strip()
    if provider.practice_name and provider.practice_name != person:
        return (
            f"{person}, {provider.practice_name}" if person else provider.practice_name
        )
    # The fax effect needs a recipient name; a directory record with no name
    # or practice still gets faxed, under a generic label.
    return person or "Care team provider"


def _care_team_providers(
    patient_id: str, role_codes: frozenset[str]
) -> list[tuple[str, ServiceProvider | None]]:
    """(role code, directory record) for each active external member with one of ``role_codes``."""
    memberships = list(
        CareTeamMembership.objects.filter(
            patient__id=patient_id,
            status=CareTeamMembershipStatus.ACTIVE,
            role_code__in=sorted(role_codes),
            staff__isnull=True,
            organizational_entity__type=OrganizationalEntity.OrganizationalEntityType.SERVICE_PROVIDER,
            organizational_entity__object_id__isnull=False,
        )
        .select_related("organizational_entity")
        .order_by("dbid")
    )
    if not memberships:
        return []
    object_ids = {m.organizational_entity.object_id for m in memberships}
    providers = {
        p.dbid: p for p in ServiceProvider.objects.filter(dbid__in=sorted(object_ids))
    }
    return [
        (m.role_code, providers.get(m.organizational_entity.object_id))
        for m in memberships
    ]


def _current_facility_address(
    patient_id: str, today: date
) -> PatientFacilityAddress | None:
    return (
        PatientFacilityAddress.objects.filter(
            patient__id=patient_id,
            state=AddressState.ACTIVE,
            facility__isnull=False,
        )
        .filter(Q(end__isnull=True) | Q(end__gte=today))
        .select_related("facility")
        .order_by("-dbid")
        .first()
    )


def resolve_recipients(
    patient_id: str, rules: list[Rule], today: date
) -> list[Recipient]:
    """Every recipient the given rules name for this patient, in rule order."""
    role_codes: set[str] = set()
    wants_facility = False
    for rule in rules:
        for spec in rule.recipients:
            if spec.type == RECIPIENT_CARE_TEAM_ROLE:
                role_codes |= spec.role_codes
            elif spec.type == RECIPIENT_FACILITY:
                wants_facility = True

    care_team = (
        _care_team_providers(patient_id, frozenset(role_codes)) if role_codes else []
    )
    facility_address = (
        _current_facility_address(patient_id, today) if wants_facility else None
    )

    recipients: list[Recipient] = []
    for rule in rules:
        for spec in rule.recipients:
            if spec.type == RECIPIENT_FIXED:
                recipients.append(
                    Recipient(rule, spec.type, spec.name, spec.fax_digits)
                )
            elif spec.type == RECIPIENT_FACILITY:
                recipients.append(_facility_recipient(rule, facility_address))
            else:
                matched = [
                    provider for code, provider in care_team if code in spec.role_codes
                ]
                if not matched:
                    recipients.append(
                        Recipient(
                            rule,
                            spec.type,
                            "",
                            None,
                            problem="no active external care team member with that role",
                        )
                    )
                for provider in matched:
                    recipients.append(_provider_recipient(rule, provider))
    return recipients


def _facility_recipient(
    rule: Rule, address: PatientFacilityAddress | None
) -> Recipient:
    if address is None:
        return Recipient(
            rule,
            RECIPIENT_FACILITY,
            "",
            None,
            problem="patient has no current facility address",
        )
    facility = address.facility
    if not facility.active:
        return Recipient(
            rule,
            RECIPIENT_FACILITY,
            facility.name,
            None,
            problem="facility is inactive",
        )
    digits = ten_digits(facility.fax_number)
    problem = None if digits else "facility has no valid fax number"
    return Recipient(rule, RECIPIENT_FACILITY, facility.name, digits, problem=problem)


def _provider_recipient(rule: Rule, provider: ServiceProvider | None) -> Recipient:
    if provider is None:
        return Recipient(
            rule,
            RECIPIENT_CARE_TEAM_ROLE,
            "",
            None,
            problem="care team member's directory record is missing",
        )
    name = _provider_name(provider)
    if not provider.is_active:
        return Recipient(
            rule,
            RECIPIENT_CARE_TEAM_ROLE,
            name,
            None,
            problem="directory record is inactive",
        )
    digits = ten_digits(provider.business_fax)
    problem = None if digits else "no valid fax number on the directory record"
    return Recipient(rule, RECIPIENT_CARE_TEAM_ROLE, name, digits, problem=problem)
