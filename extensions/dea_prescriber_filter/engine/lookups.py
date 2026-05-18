"""Lookup helpers for populating delegation UI dropdowns."""

from __future__ import annotations

from typing import Any

from canvas_sdk.v1.data import Staff

DEFAULT_NPI = "1111155556"


def get_active_providers() -> list[dict[str, Any]]:
    """Return active providers, deduplicated by NPI. One entry per unique provider."""
    seen_npis: set[str] = set()
    results: list[dict[str, Any]] = []
    for staff in Staff.objects.filter(active=True, roles__role_type="PROVIDER").distinct().order_by("last_name", "first_name"):
        npi = staff.npi_number or ""
        npi_str = str(npi)
        # Deduplicate by NPI (skip default NPI for dedup purposes)
        if npi_str and npi_str != DEFAULT_NPI:
            if npi_str in seen_npis:
                continue
            seen_npis.add(npi_str)
        results.append(
            {
                "id": str(staff.id),
                "name": f"{staff.first_name} {staff.last_name}".strip(),
                "npi_number": npi_str,
            }
        )
    return results


def get_active_staff() -> list[dict[str, Any]]:
    """Return active staff, deduplicated by NPI. One entry per unique person."""
    seen_npis: set[str] = set()
    results: list[dict[str, Any]] = []
    for staff in Staff.objects.filter(active=True).distinct().order_by("last_name", "first_name"):
        npi = staff.npi_number or ""
        npi_str = str(npi)
        if npi_str and npi_str != DEFAULT_NPI:
            if npi_str in seen_npis:
                continue
            seen_npis.add(npi_str)
        results.append(
            {
                "id": str(staff.id),
                "name": f"{staff.first_name} {staff.last_name}".strip(),
            }
        )
    return results


def get_staff_name(staff_id: str) -> str:
    """Resolve a staff UUID to a name, even if inactive."""
    try:
        staff = Staff.objects.get(id=staff_id)
        return f"{staff.first_name} {staff.last_name}".strip()
    except Staff.DoesNotExist:
        return staff_id
