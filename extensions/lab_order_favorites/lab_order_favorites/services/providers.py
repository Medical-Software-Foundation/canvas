"""Lookups for selectable ordering providers.

An ordering provider is an active Staff member with a usable NPI. Placeholder
NPIs (e.g. the all-ones test value) are excluded so they never appear as a
real ordering provider.
"""

from canvas_sdk.v1.data import Staff

# Canvas assigns this default placeholder NPI to staff who have no real NPI, so
# it is excluded everywhere - it never identifies a real ordering provider.
EXCLUDED_NPIS = {"1111155556"}


def list_ordering_providers(search: str = "") -> list[dict[str, str]]:
    """Return active providers with a usable NPI as [{id, name, npi}].

    Optional case-insensitive search matches on first/last name or NPI.
    """
    providers = (
        Staff.objects.filter(active=True)
        .exclude(npi_number="")
        .exclude(npi_number__isnull=True)
        .exclude(npi_number__in=EXCLUDED_NPIS)
        .order_by("last_name", "first_name")
    )

    results = []
    needle = search.strip().lower()
    for staff in providers:
        entry = _provider_dict(staff)
        if needle and needle not in f"{entry['name']} {entry['npi']}".lower():
            continue
        results.append(entry)
    return results


def resolve_provider(provider_id: str) -> tuple[dict[str, str] | None, str]:
    """Resolve a selectable provider by Staff id.

    Returns ({id, name, npi}, "") if the id is an active provider with a usable
    NPI, otherwise (None, reason).
    """
    value = provider_id.strip()
    if not value:
        return None, "ordering provider is required"

    # Staff.id matches a hex string, not a UUID object - query by the raw value.
    try:
        staff = Staff.objects.get(id=value)
    except Staff.DoesNotExist:
        return None, f"ordering provider '{value}' not found"

    if not staff.active:
        return None, "ordering provider is not active"
    npi = (staff.npi_number or "").strip()
    if not npi or npi in EXCLUDED_NPIS:
        return None, "ordering provider does not have a valid NPI"

    return _provider_dict(staff), ""


def _provider_dict(staff: Staff) -> dict[str, str]:
    """Shape a Staff member as a provider option."""
    first = getattr(staff, "first_name", "") or ""
    last = getattr(staff, "last_name", "") or ""
    return {
        "id": str(staff.id),
        "name": f"{first} {last}".strip(),
        "npi": (staff.npi_number or "").strip(),
    }
