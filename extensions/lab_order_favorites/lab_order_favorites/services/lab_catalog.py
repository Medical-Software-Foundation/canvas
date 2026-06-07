"""Lookups and validation against the instance-configured lab catalog.

The instance's lab partners and the tests they offer are the source of truth.
A favorite's saved test codes are always re-validated against this catalog
before a command is built, so a stale code can never reach the note.
"""

from typing import Any
from uuid import UUID

from canvas_sdk.v1.data import LabPartner, LabPartnerTest
from logger import log


def list_active_partners() -> list[dict[str, str]]:
    """Return active lab partners as [{id, name}] sorted by name."""
    partners = LabPartner.objects.filter(active=True).order_by("name")
    return [{"id": str(p.id), "name": p.name or ""} for p in partners]


def list_tests_for_partner(partner_id: str, search: str = "") -> list[dict[str, str]]:
    """Return tests offered by a partner as [{order_code, order_name, cpt_code}].

    Only tests with a non-blank order_code are returned (a blank code cannot be
    ordered). An optional case-insensitive search filters on name or code.
    """
    tests = LabPartnerTest.objects.filter(lab_partner__id=partner_id).exclude(
        order_code=""
    )
    if search:
        needle = search.strip().lower()
        results = []
        for t in tests:
            haystack = f"{t.order_name or ''} {t.order_code or ''} {t.keywords or ''}".lower()
            if needle in haystack:
                results.append(_test_dict(t))
        return results
    return [_test_dict(t) for t in tests]


def resolve_partner(name_or_id: str) -> tuple[LabPartner | None, str]:
    """Resolve a lab partner from a CSV cell that may hold a name or an ID.

    Matches an active partner by exact (case-insensitive) name first, then by
    UUID. Returns (partner, "") on success or (None, reason) on failure.
    Ambiguous name matches are rejected rather than guessed.
    """
    value = name_or_id.strip()
    if not value:
        return None, "lab partner is required"

    by_name = list(LabPartner.objects.filter(active=True, name__iexact=value))
    if len(by_name) == 1:
        return by_name[0], ""
    if len(by_name) > 1:
        return None, f"lab partner name '{value}' is ambiguous (matches {len(by_name)} partners) - use the ID"

    parsed = _parse_uuid(value)
    if parsed is not None:
        try:
            partner = LabPartner.objects.get(id=parsed)
        except LabPartner.DoesNotExist:
            return None, f"lab partner '{value}' not found"
        if not partner.active:
            return None, f"lab partner '{partner.name}' is not active"
        return partner, ""

    return None, f"lab partner '{value}' not found"


def check_availability(partner_id: str, order_codes: list[str]) -> dict[str, Any]:
    """Validate a favorite's partner and test codes against the live catalog.

    Returns a dict:
        partner_found: bool
        partner_active: bool
        partner_name: str
        stale: list[str]   - order_codes no longer offered by the partner
        valid: list[str]   - order_codes still available, in the input order
    """
    parsed = _parse_uuid(partner_id)
    if parsed is None:
        return {
            "partner_found": False,
            "partner_active": False,
            "partner_name": "",
            "stale": list(order_codes),
            "valid": [],
        }

    try:
        partner = LabPartner.objects.get(id=parsed)
    except LabPartner.DoesNotExist:
        return {
            "partner_found": False,
            "partner_active": False,
            "partner_name": "",
            "stale": list(order_codes),
            "valid": [],
        }

    available = set(
        LabPartnerTest.objects.filter(lab_partner__id=partner_id)
        .exclude(order_code="")
        .values_list("order_code", flat=True)
    )

    valid = [code for code in order_codes if code in available]
    stale = [code for code in order_codes if code not in available]

    if stale:
        log.info(f"Lab favorite has {len(stale)} stale codes for partner {partner_id}")

    return {
        "partner_found": True,
        "partner_active": bool(partner.active),
        "partner_name": partner.name or "",
        "stale": stale,
        "valid": valid,
    }


def _test_dict(test: LabPartnerTest) -> dict[str, str]:
    """Shape a LabPartnerTest for the UI and storage."""
    return {
        "order_code": test.order_code or "",
        "order_name": test.order_name or "",
        "cpt_code": test.cpt_code or "",
    }


def _parse_uuid(value: str) -> UUID | None:
    """Parse a string into a UUID, returning None if it is not a valid UUID."""
    try:
        return UUID(value)
    except (ValueError, AttributeError):
        return None
