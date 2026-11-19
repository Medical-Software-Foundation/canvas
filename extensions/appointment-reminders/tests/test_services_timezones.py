"""Tests for services/timezones.py — address to IANA zone.

The point of this module is that a patient two zones from the clinic reads
their own local time in the message, so the cases that matter are the ones
where a naive state lookup gets the hour wrong.
"""

from __future__ import annotations

import zoneinfo

from appointment_reminders.services.timezones import (
    _SPLIT_STATE_PREFIXES,
    _STATE_ZONES,
    RESOLVABLE_ZONES,
    zone_for_address,
)


# ---- single-zone states ----

def test_resolves_a_state_that_sits_in_one_zone() -> None:
    assert zone_for_address("WA", "98101") == "America/Los_Angeles"
    assert zone_for_address("GA", "30301") == "America/New_York"
    assert zone_for_address("CO", "80202") == "America/Denver"


def test_arizona_gets_phoenix_rather_than_denver() -> None:
    """Arizona does not observe DST, so Denver is wrong for half the year."""
    assert zone_for_address("AZ", "85001") == "America/Phoenix"


def test_state_resolves_without_a_postal_code() -> None:
    assert zone_for_address("CA") == "America/Los_Angeles"


def test_state_code_is_case_and_whitespace_insensitive() -> None:
    assert zone_for_address(" ca ", "94105") == "America/Los_Angeles"


# ---- split states ----

def test_florida_panhandle_is_central_and_the_rest_eastern() -> None:
    assert zone_for_address("FL", "32502") == "America/Chicago"  # Pensacola
    assert zone_for_address("FL", "33101") == "America/New_York"  # Miami


def test_west_texas_is_mountain_and_the_rest_central() -> None:
    assert zone_for_address("TX", "79901") == "America/Denver"  # El Paso
    assert zone_for_address("TX", "78701") == "America/Chicago"  # Austin


def test_east_tennessee_is_eastern_and_the_rest_central() -> None:
    assert zone_for_address("TN", "37902") == "America/New_York"  # Knoxville
    assert zone_for_address("TN", "37402") == "America/New_York"  # Chattanooga
    assert zone_for_address("TN", "37311") == "America/New_York"  # Cleveland
    assert zone_for_address("TN", "37201") == "America/Chicago"  # Nashville


def test_northwest_indiana_is_central_and_the_rest_eastern() -> None:
    assert zone_for_address("IN", "46402") == "America/Chicago"  # Gary
    assert zone_for_address("IN", "46204") == "America/New_York"  # Indianapolis


def test_northern_idaho_is_pacific_and_the_rest_mountain() -> None:
    assert zone_for_address("ID", "83814") == "America/Los_Angeles"  # Coeur d'Alene
    assert zone_for_address("ID", "83702") == "America/Boise"  # Boise


def test_western_kentucky_is_central_and_the_rest_eastern() -> None:
    assert zone_for_address("KY", "42001") == "America/Chicago"  # Paducah
    assert zone_for_address("KY", "40202") == "America/New_York"  # Louisville


def test_a_zip_prefix_never_applies_outside_its_own_state() -> None:
    """79xxx is El Paso's, so it must not pull a Georgia address to Mountain.

    Prefixes are keyed by state for exactly this reason: a transposed or
    mistyped ZIP on a chart should degrade to the state's zone, not to
    whichever state happens to own that prefix.
    """
    assert zone_for_address("GA", "79901") == "America/New_York"


def test_postal_code_punctuation_is_ignored() -> None:
    assert zone_for_address("TX", "79901-1234") == "America/Denver"
    assert zone_for_address("TX", " 79901 ") == "America/Denver"


# ---- refusing to guess ----

def test_returns_empty_for_a_non_us_country() -> None:
    """A patient in Ontario must not be placed on US Eastern by a state match."""
    assert zone_for_address("ON", "M5H 2N2", "CA") == ""
    assert zone_for_address("TX", "79901", "Mexico") == ""


def test_blank_country_is_treated_as_domestic() -> None:
    """Domestic addresses routinely leave country unset."""
    assert zone_for_address("TX", "78701", "") == "America/Chicago"
    assert zone_for_address("TX", "78701", "United States") == "America/Chicago"


def test_returns_empty_for_a_missing_or_unknown_state() -> None:
    assert zone_for_address("", "78701") == ""
    assert zone_for_address("ZZ", "78701") == ""


def test_puerto_rico_resolves() -> None:
    assert zone_for_address("PR", "00901") == "America/Puerto_Rico"


# ---- table integrity ----

def test_every_zone_in_the_tables_is_a_real_iana_zone() -> None:
    """A typo here would raise at send time, inside the cron's per-row except."""
    zones = set(_STATE_ZONES.values())
    for prefixes in _SPLIT_STATE_PREFIXES.values():
        zones.update(prefixes.values())
    for zone in zones:
        zoneinfo.ZoneInfo(zone)


def test_resolvable_zones_covers_everything_the_resolver_can_return() -> None:
    """The reminder cron gates its scan on this set, so a zone missing from it
    is a day-out reminder that silently never fires for those patients."""
    for zone in _STATE_ZONES.values():
        assert zone in RESOLVABLE_ZONES
    for prefixes in _SPLIT_STATE_PREFIXES.values():
        for zone in prefixes.values():
            assert zone in RESOLVABLE_ZONES


def test_split_state_prefixes_only_cover_states_the_map_knows() -> None:
    for state in _SPLIT_STATE_PREFIXES:
        assert state in _STATE_ZONES


def test_split_prefixes_actually_differ_from_their_state_default() -> None:
    """A prefix that agrees with its state default is dead weight, and usually
    means the split was recorded on the wrong side."""
    for state, prefixes in _SPLIT_STATE_PREFIXES.items():
        for prefix, zone in prefixes.items():
            assert zone != _STATE_ZONES[state], f"{state} {prefix}"
