"""Provider lookup by name or NPI number."""

from __future__ import annotations

from typing import Any

from canvas_sdk.v1.data import Staff


def resolve_provider_id(
    provider_id: str = "",
    provider_npi: str = "",
) -> str:
    """Return canonical Staff UUID from either a direct ID or NPI lookup.

    Raises ValueError if neither parameter is provided, the NPI is not found,
    or multiple staff match the same NPI.
    """
    if provider_id:
        return provider_id

    if not provider_npi:
        raise ValueError("Either provider_id or provider_npi is required")

    try:
        staff = Staff.objects.get(npi_number=provider_npi)
        return str(staff.id)
    except Staff.DoesNotExist:
        raise ValueError(f"No provider found with NPI {provider_npi}")
    except Staff.MultipleObjectsReturned:
        raise ValueError(f"Multiple providers found with NPI {provider_npi}")


def search_providers(query: str, active_only: bool = True) -> list[dict[str, Any]]:
    """Search staff by name or NPI prefix.

    If *query* is all digits it is treated as an NPI prefix (``startswith``).
    Otherwise it is matched against first/last name (``icontains``).

    Returns at most 50 results.
    """
    if not query or not query.strip():
        return []

    query = query.strip()
    qs = Staff.objects.all()

    if active_only:
        qs = qs.filter(active=True)

    if query.isdigit():
        qs = qs.filter(npi_number__startswith=query)
    else:
        parts = query.split(None, 1)
        if len(parts) == 2:
            qs = qs.filter(
                first_name__icontains=parts[0],
                last_name__icontains=parts[1],
            )
        else:
            qs = qs.filter(first_name__icontains=query) | qs.filter(
                last_name__icontains=query
            )

    results: list[dict[str, Any]] = []
    for staff in qs[:50]:
        results.append(
            {
                "id": str(staff.id),
                "first_name": staff.first_name,
                "last_name": staff.last_name,
                "npi_number": staff.npi_number,
            }
        )
    return results


def get_provider_display(provider_id: str) -> dict[str, str]:
    """Return display info for a single provider.

    Returns dict with ``id``, ``name``, and ``npi_number``.
    Falls back to the raw ID when the staff record cannot be found.
    """
    try:
        staff = Staff.objects.get(id=provider_id)
        return {
            "id": str(staff.id),
            "name": f"{staff.first_name} {staff.last_name}".strip(),
            "npi_number": staff.npi_number or "",
        }
    except Staff.DoesNotExist:
        return {"id": provider_id, "name": "", "npi_number": ""}


def get_provider_displays(provider_ids: list[str]) -> dict[str, dict[str, str]]:
    """Batch lookup of display info for multiple providers."""
    result: dict[str, dict[str, str]] = {}
    if not provider_ids:
        return result

    unique_ids = list(set(provider_ids))
    staff_qs = Staff.objects.filter(id__in=unique_ids)
    found: dict[str, Any] = {}
    for staff in staff_qs:
        found[str(staff.id)] = staff

    for pid in unique_ids:
        staff = found.get(pid)
        if staff:
            result[pid] = {
                "id": str(staff.id),
                "name": f"{staff.first_name} {staff.last_name}".strip(),
                "npi_number": staff.npi_number or "",
            }
        else:
            result[pid] = {"id": pid, "name": "", "npi_number": ""}

    return result
