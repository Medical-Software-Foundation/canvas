"""Resolve a US mailing address to an IANA timezone.

``Patient.last_known_timezone`` is the field a plugin is supposed to read for a
patient's zone, and it is the only patient timezone column in the schema. In
practice nothing in routine charting writes it: it is populated by the FHIR
Patient ``tz-code`` extension, so across the production fleet it holds a value
on a handful of patient rows in total and is NULL everywhere else. A resolver
that stops there therefore renders every message in the one configured clinic
zone, which is what a patient two zones away sees today.

The patient's own address is the populated stand-in. On the instance this was
measured against, 1,340 of 1,353 appointments in the next 30 days had a patient
address carrying a state code.

Accuracy, stated plainly: a two-letter state resolves exactly for the 44 states
that sit in one zone. For the states split across two, the three-digit ZIP
prefixes below carry the split where a prefix falls cleanly on one side of the
line. Where it does not — a handful of border counties in Kentucky, the four
Central counties of Michigan's Upper Peninsula, the Mountain corners of Kansas
and Nebraska, the Navajo Nation's observance of DST inside Arizona — the state
default wins and can be wrong by an hour. Setting ``last_known_timezone`` on
those patients through the FHIR ``tz-code`` extension overrides everything here.
"""

_EASTERN = "America/New_York"
_CENTRAL = "America/Chicago"
_MOUNTAIN = "America/Denver"
_ARIZONA = "America/Phoenix"
_PACIFIC = "America/Los_Angeles"
_ALASKA = "America/Anchorage"
_HAWAII = "Pacific/Honolulu"
_BOISE = "America/Boise"
_PUERTO_RICO = "America/Puerto_Rico"
_GUAM = "Pacific/Guam"
_SAMOA = "Pacific/Pago_Pago"

# The state's predominant zone. Split states appear here under the side holding
# most of their population; _SPLIT_STATE_PREFIXES below carries the exceptions.
_STATE_ZONES: dict[str, str] = {
    # Eastern
    "CT": _EASTERN, "DC": _EASTERN, "DE": _EASTERN, "FL": _EASTERN, "GA": _EASTERN,
    "IN": _EASTERN, "KY": _EASTERN, "MA": _EASTERN, "MD": _EASTERN, "ME": _EASTERN,
    "MI": _EASTERN, "NC": _EASTERN, "NH": _EASTERN, "NJ": _EASTERN, "NY": _EASTERN,
    "OH": _EASTERN, "PA": _EASTERN, "RI": _EASTERN, "SC": _EASTERN, "VA": _EASTERN,
    "VT": _EASTERN, "WV": _EASTERN,
    # Central
    "AL": _CENTRAL, "AR": _CENTRAL, "IA": _CENTRAL, "IL": _CENTRAL, "KS": _CENTRAL,
    "LA": _CENTRAL, "MN": _CENTRAL, "MO": _CENTRAL, "MS": _CENTRAL, "ND": _CENTRAL,
    "NE": _CENTRAL, "OK": _CENTRAL, "SD": _CENTRAL, "TN": _CENTRAL, "TX": _CENTRAL,
    "WI": _CENTRAL,
    # Mountain
    "CO": _MOUNTAIN, "MT": _MOUNTAIN, "NM": _MOUNTAIN, "UT": _MOUNTAIN, "WY": _MOUNTAIN,
    "ID": _BOISE,
    "AZ": _ARIZONA,
    # Pacific and beyond
    "CA": _PACIFIC, "NV": _PACIFIC, "OR": _PACIFIC, "WA": _PACIFIC,
    "AK": _ALASKA, "HI": _HAWAII,
    # Territories
    "PR": _PUERTO_RICO, "VI": _PUERTO_RICO,
    "GU": _GUAM, "MP": _GUAM, "AS": _SAMOA,
}

# Three-digit ZIP prefix → zone for the states split across two zones, keyed by
# state so a prefix can never be applied to an address in the wrong one. Only
# prefixes that fall entirely (or all but entirely) on the minority side of the
# line belong here; a mixed prefix is left out so the state default handles it
# rather than a coin flip.
_SPLIT_STATE_PREFIXES: dict[str, dict[str, str]] = {
    # Florida panhandle west of the Apalachicola River
    "FL": {
        "324": _CENTRAL,  # Panama City, Marianna
        "325": _CENTRAL,  # Pensacola, Fort Walton Beach
    },
    # Northwest and southwest Indiana
    "IN": {
        "463": _CENTRAL,  # Gary, Hammond
        "464": _CENTRAL,  # Gary, Merrillville
        "476": _CENTRAL,  # Evansville
        "477": _CENTRAL,  # Evansville
    },
    # Western Kentucky
    "KY": {
        "420": _CENTRAL,  # Paducah
        "421": _CENTRAL,  # Bowling Green
        "422": _CENTRAL,  # Bowling Green
        "423": _CENTRAL,  # Owensboro
        "424": _CENTRAL,  # Owensboro, Henderson
    },
    # East Tennessee
    "TN": {
        "373": _EASTERN,  # Cleveland, Athens
        "374": _EASTERN,  # Chattanooga
        "376": _EASTERN,  # Johnson City, Kingsport
        "377": _EASTERN,  # Knoxville
        "378": _EASTERN,  # Knoxville
        "379": _EASTERN,  # Knoxville
    },
    # West Texas
    "TX": {
        "798": _MOUNTAIN,  # El Paso outskirts
        "799": _MOUNTAIN,  # El Paso
    },
    # Western Dakotas
    "ND": {"586": _MOUNTAIN},  # Dickinson
    "SD": {"577": _MOUNTAIN},  # Rapid City
    # Eastern Oregon
    "OR": {"979": _MOUNTAIN},  # Malheur County
    # Northern Idaho, north of the Salmon River
    "ID": {
        "835": _PACIFIC,  # Lewiston, Moscow, Grangeville
        "838": _PACIFIC,  # Coeur d'Alene, Sandpoint
    },
}

# Every zone this module can return. The reminder cron uses it to decide whether
# any patient's local send time could be firing right now, before it runs the
# appointment query.
RESOLVABLE_ZONES: frozenset[str] = frozenset(_STATE_ZONES.values()) | {
    zone for prefixes in _SPLIT_STATE_PREFIXES.values() for zone in prefixes.values()
}

# Blank is included because a domestic address frequently leaves country unset.
_DOMESTIC_COUNTRIES = {"", "US", "USA", "UNITED STATES", "UNITED STATES OF AMERICA"}


def zone_for_address(state_code: str, postal_code: str = "", country: str = "") -> str:
    """The IANA zone for a US address, or ``""`` when it cannot be resolved.

    Returns empty rather than guessing for a non-US country, an unrecognized
    state, or a missing one, so the caller falls through to its own default
    instead of putting a patient abroad on Eastern time.
    """
    if (country or "").strip().upper() not in _DOMESTIC_COUNTRIES:
        return ""

    state = (state_code or "").strip().upper()
    if state not in _STATE_ZONES:
        return ""

    digits = "".join(c for c in (postal_code or "") if c.isdigit())
    if len(digits) >= 3:
        prefixed = _SPLIT_STATE_PREFIXES.get(state, {}).get(digits[:3])
        if prefixed:
            return prefixed

    return _STATE_ZONES[state]
