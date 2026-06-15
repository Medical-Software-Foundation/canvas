"""Static, non-clinical instrument config.

Only display label and max score (for the "/max" denominator and a fixed
y-axis). No severity thresholds, no direction, no cadence - the dashboard
presents data only.
"""

from __future__ import annotations

from typing import NamedTuple


class Instrument(NamedTuple):
    label: str
    max_score: int | None  # None -> y-axis auto-scales, denominator omitted


# Keyed by a normalized match key (lowercase substring of the Observation name).
# Match is best-effort by name; unknown instruments still render generically.
INSTRUMENTS: dict[str, Instrument] = {
    "phq-9": Instrument("PHQ-9", 27),
    "phq9": Instrument("PHQ-9", 27),
    "gad-7": Instrument("GAD-7", 21),
    "gad7": Instrument("GAD-7", 21),
    "audit": Instrument("AUDIT", 40),
    "asrs": Instrument("ASRS (Adult ADHD)", 24),
    "adhd": Instrument("ASRS (Adult ADHD)", 24),
    "mdq": Instrument("Bipolar (MDQ)", 13),
    "epds": Instrument("EPDS (Postpartum)", 30),
    "postpartum": Instrument("EPDS (Postpartum)", 30),
    "aims": Instrument("AIMS", 28),
    "pcl-5": Instrument("PCL-5 (PTSD)", 80),
    "pcl5": Instrument("PCL-5 (PTSD)", 80),
    "ptsd": Instrument("PCL-5 (PTSD)", 80),
    # Standard LOINC codes for these instruments, in case a scored survey
    # Observation is named by its questionnaire code rather than its display
    # name. ("asrs_v11_parta" already matches the "asrs" key above.)
    "44249-1": Instrument("PHQ-9", 27),
    "69737-5": Instrument("GAD-7", 21),
    "72110-0": Instrument("AUDIT", 40),
    "99046-5": Instrument("EPDS (Postpartum)", 30),
    "96762-0": Instrument("PCL-5 (PTSD)", 80),
}


def resolve_instrument(name: str) -> Instrument:
    """Map an Observation name to a known Instrument, or a generic fallback.

    Falls back to the raw name with no max score when no key matches.
    """
    lowered = name.lower()
    for key, inst in INSTRUMENTS.items():
        if key in lowered:
            return inst
    return Instrument(name, None)
