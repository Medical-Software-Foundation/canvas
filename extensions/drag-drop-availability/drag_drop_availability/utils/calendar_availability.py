"""Calendar title parsing for the availability manager.

The availability manager only needs to read the structured ``{Staff}: {Type}:
{Location}`` calendar title. Slot generation, recurrence expansion, and
availability-window computation live in the scheduler plugin and are
intentionally not part of this standalone availability tool.
"""

from __future__ import annotations


def parse_calendar_title(title: str) -> tuple[str, str, str | None]:
    """Parse a calendar title into (staff_name, calendar_type, location_name | None).

    Format: "{Staff Name}: {Type}" or "{Staff Name}: {Type}: {Location Name}"
    Examples:
        "Christopher Taylor: Clinic: Florida location"
            -> ("Christopher Taylor", "Clinic", "Florida location")
        "Richard Wilson: Clinic"
            -> ("Richard Wilson", "Clinic", None)
    """
    parts = [p.strip() for p in title.split(":")]
    if len(parts) >= 3:
        # Rejoin parts 2+ in case location name itself contains ":"
        return parts[0], parts[1], ":".join(parts[2:]).strip()
    if len(parts) == 2:
        return parts[0], parts[1], None
    return title.strip(), "", None
