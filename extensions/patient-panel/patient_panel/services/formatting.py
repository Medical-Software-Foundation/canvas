"""Date/timezone formatting, visit-recency thresholds, address/coverage
rendering, and daily-flag parsing.

Pure functions. Timezone resolution + its cache stay on the API class; callers
pass the resolved `tz` into format_local.
"""

from typing import Any

import arrow


def format_local(dt: Any, fmt: str, tz: str) -> str:
    """Format a datetime in the given display timezone."""
    return arrow.get(dt).to(tz).format(fmt)


def compare_threshold(date: Any, secrets: dict[str, Any]) -> str:
    """Classify how recent `date` is into green/yellow/red highlight bands."""
    now = arrow.utcnow()
    date = arrow.get(date)
    if date >= now.shift(days=-secrets["highlight_green"]):
        return "green"
    elif date >= now.shift(days=-secrets["highlight_yellow"]):
        return "yellow"
    return "red"


def get_coverage(patient: Any) -> str | None:
    """Get coverage issuer name for a patient (uses prefetched coverages)."""
    coverages = list(patient.coverages.all())
    return coverages[-1].issuer.name if coverages and coverages[-1].issuer else None


# PatientAddress.use values, in display priority order. "old" addresses
# are dropped entirely.
ADDRESS_USE_PRIORITY = ("home", "work", "temp")


def format_primary_address(patient: Any) -> str:
    """Render the patient's primary address as a single string.

    Picks one address per patient: prefers state="active" rows, then ranks by
    use (home → work → temp). "Old" addresses are excluded. Falls back to
    whatever address exists if nothing matches.
    """
    addresses = list(patient.addresses.all())
    if not addresses:
        return ""

    active = [
        a for a in addresses
        if getattr(a, "state", "active") != "deleted"
        and getattr(a, "use", "") != "old"
    ]
    candidates = active or addresses

    def _rank(a: Any) -> int:
        try:
            return ADDRESS_USE_PRIORITY.index(a.use)
        except ValueError:
            return len(ADDRESS_USE_PRIORITY)

    addr = sorted(candidates, key=_rank)[0]

    parts: list[str] = []
    if addr.line1:
        parts.append(addr.line1)
    if addr.line2:
        parts.append(addr.line2)
    if addr.city:
        parts.append(addr.city)
    state_zip = " ".join(p for p in (addr.state_code, addr.postal_code) if p)
    if state_zip:
        parts.append(state_zip)
    return ", ".join(parts)


def get_flag_color(
    patient: Any,
    metadata_by_key: dict[str, Any] | None = None,
) -> str | None:
    """Get flag color for patient. Returns 'green', 'yellow', 'red', or None.

    When `metadata_by_key` is supplied (built by the caller from the prefetched
    `patient.metadata` relation) the lookup is O(1) and avoids re-iterating the
    prefetched list once per patient.
    """
    today_str = arrow.now().format("YYYY-MM-DD")
    if metadata_by_key is not None:
        flag_metadata = metadata_by_key.get("daily_flag")
    else:
        flag_metadata = next(
            (m for m in patient.metadata.all() if m.key == "daily_flag"),
            None,
        )
    if not flag_metadata or not flag_metadata.value:
        return None
    parts: list[str] = flag_metadata.value.split(":")
    if len(parts) == 2 and parts[0] == today_str:
        return parts[1]
    if flag_metadata.value == today_str:
        return "green"
    return None


def is_patient_flagged(
    patient: Any,
    metadata_by_key: dict[str, Any] | None = None,
) -> bool:
    """Check if patient has today's daily flag."""
    return get_flag_color(patient, metadata_by_key) is not None
