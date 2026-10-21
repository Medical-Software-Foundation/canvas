"""The instance's lab partners and tests, and the staff who can be an ordering provider.

The live lab catalog is the source of truth. A lab favorite's test codes are checked against it
again every time the favorite is added to a note, so a code the lab stopped offering never reaches a
note. Carried over from lab_order_favorites (services/lab_catalog.py and services/providers.py).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.db.models import Q

from canvas_sdk.v1.data import LabPartner, LabPartnerTest, Staff

# Canvas gives this placeholder NPI to staff who have no real one; it never identifies a provider.
PLACEHOLDER_NPIS = {"1111155556"}


def parse_uuid(value: str) -> UUID | None:
    try:
        return UUID(str(value))
    except (ValueError, AttributeError):
        return None


def active_partners() -> list[dict[str, str]]:
    return [{"id": str(p.id), "name": p.name or ""} for p in LabPartner.objects.filter(active=True).order_by("name")]


def partner_tests(partner_id: str, search: str = "", limit: int = 50) -> list[dict[str, str]]:
    """Tests a partner offers, as [{code, name}]. Tests with no order code can't be ordered and are left out.

    Each search word must appear in the test's name, code, or keywords. The filtering runs in the
    database, since a lab's catalog can hold thousands of tests.
    """
    if parse_uuid(partner_id) is None:
        return []
    tests = LabPartnerTest.objects.filter(lab_partner__id=partner_id).exclude(order_code="")
    for word in search.split():
        tests = tests.filter(Q(order_name__icontains=word) | Q(order_code__icontains=word) | Q(keywords__icontains=word))
    rows = tests.order_by("order_name").values_list("order_code", "order_name")[:limit]
    return [{"code": code or "", "name": name or ""} for code, name in rows]


def resolve_partner(value: str) -> tuple[LabPartner | None, str]:
    """An active lab partner from a name or an id. Ambiguous names are refused rather than guessed."""
    value = value.strip()
    if not value:
        return None, "the lab partner is missing"
    by_name = list(LabPartner.objects.filter(active=True, name__iexact=value)[:2])
    if len(by_name) == 1:
        return by_name[0], ""
    if len(by_name) > 1:
        return None, f"more than one lab partner is named {value}"
    if parse_uuid(value) is not None:
        partner = LabPartner.objects.filter(id=value).first()
        if partner is not None:
            return (partner, "") if partner.active else (None, f"{partner.name} is not an active lab partner")
    return None, f"no active lab partner is named {value}"


def check_tests(partner_id: str, codes: list[str]) -> dict[str, Any]:
    """Check a partner and test codes against the live catalog.

    Returns partner_found, partner_active, partner_name, valid (codes still offered, in order) and
    stale (codes the partner no longer offers).
    """
    partner = LabPartner.objects.filter(id=partner_id).first() if parse_uuid(partner_id) else None
    if partner is None:
        return {"partner_found": False, "partner_active": False, "partner_name": "", "valid": [], "stale": list(codes)}
    offered = set(
        LabPartnerTest.objects.filter(lab_partner__id=partner_id, order_code__in=codes).values_list("order_code", flat=True)
    )
    return {
        "partner_found": True,
        "partner_active": bool(partner.active),
        "partner_name": partner.name or "",
        "valid": [code for code in codes if code in offered],
        "stale": [code for code in codes if code not in offered],
    }


def resolve_tests(partner_id: str, values: list[str]) -> tuple[list[dict[str, str]], list[str], list[str]]:
    """Match test order codes or exact test names to the partner's catalog.

    Returns (tests, not_found, shared): shared are names more than one test has, which are refused rather
    than guessed.

    Only the tests named in values are read, not the whole catalog.
    """
    wanted = [v.strip() for v in values if v.strip()]
    named = Q()
    for value in wanted:
        named |= Q(order_code__iexact=value) | Q(order_name__iexact=value)
    catalog = list(LabPartnerTest.objects.filter(named, lab_partner__id=partner_id).exclude(order_code="")) if wanted else []
    by_code = {t.order_code.lower(): t for t in catalog if t.order_code}
    by_name: dict[str, list[LabPartnerTest]] = {}
    for test in catalog:
        by_name.setdefault((test.order_name or "").lower(), []).append(test)
    found: list[dict[str, str]] = []
    missing: list[str] = []
    shared: list[str] = []
    for value in wanted:
        key = value.lower()
        test = by_code.get(key)
        if test is None and len(by_name.get(key, [])) == 1:
            test = by_name[key][0]
        if test is None:
            (shared if len(by_name.get(key, [])) > 1 else missing).append(value)
        elif test.order_code not in {t["code"] for t in found}:
            found.append({"code": test.order_code, "name": test.order_name or ""})
    return found, missing, shared


def _usable_npi(staff: Staff) -> bool:
    npi = (staff.npi_number or "").strip()
    return bool(npi) and npi not in PLACEHOLDER_NPIS


def provider_dict(staff: Staff) -> dict[str, str]:
    return {
        "id": str(staff.id),
        "name": f"{staff.first_name or ''} {staff.last_name or ''}".strip(),
        "npi": (staff.npi_number or "").strip(),
    }


def ordering_providers(search: str = "", limit: int = 50) -> list[dict[str, str]]:
    """Active staff with a usable NPI, as [{id, name, npi}]."""
    needle = search.strip().lower()
    staff = (
        Staff.objects.only("id", "first_name", "last_name", "npi_number")
        .filter(active=True)
        .exclude(npi_number="")
        .exclude(npi_number__isnull=True)
        .exclude(npi_number__in=PLACEHOLDER_NPIS)
        .order_by("last_name", "first_name")
    )
    results: list[dict[str, str]] = []
    for person in staff:
        entry = provider_dict(person)
        if needle and needle not in f"{entry['name']} {entry['npi']}".lower():
            continue
        results.append(entry)
        if len(results) >= limit:
            break
    return results


def usable_provider(staff_id: str | None) -> Staff | None:
    """The staff member, if they are active and have a usable NPI."""
    if not staff_id:
        return None
    staff = Staff.objects.filter(id=staff_id, active=True).first()
    return staff if staff is not None and _usable_npi(staff) else None
