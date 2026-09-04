"""Tests for services/templates.py — pure rendering helpers.

Avoid the DB-touching helpers (`get_template_variables`, `get_form_template_variables`,
`get_message_template_variables`) since they require fully-mocked SDK objects.
The pure helpers below cover the bulk of the rendering logic.
"""

from __future__ import annotations

import zoneinfo
from datetime import datetime
from unittest.mock import MagicMock

from appointment_reminders.services.templates import (
    _resolve_timezone,
    _tz_abbrev,
    render_template,
    resolve_timezone_name,
)


def _address(state_code="", postal_code="", country="", use="home", state="active"):
    address = MagicMock()
    address.state_code = state_code
    address.postal_code = postal_code
    address.country = country
    address.use = use
    address.state = state
    return address


def _patient_with_addresses(*addresses, last_known_timezone=None):
    """A patient stub whose `addresses` behaves like a prefetched relation."""
    patient = MagicMock()
    patient.last_known_timezone = last_known_timezone
    patient.addresses.all.return_value = list(addresses)
    return patient


# ---- render_template ----

def test_render_template_replaces_double_brace_placeholders() -> None:
    result = render_template("Hi {{patient_name}}, due {{due_date}}", {
        "patient_name": "Jane",
        "due_date": "2026-06-01",
    })
    assert result == "Hi Jane, due 2026-06-01"


def test_render_template_leaves_unknown_placeholders_alone() -> None:
    result = render_template("Hi {{name}}, code {{unknown}}", {"name": "Jane"})
    assert result == "Hi Jane, code {{unknown}}"


def test_render_template_handles_non_string_values() -> None:
    result = render_template("Count: {{n}}", {"n": 42})
    assert result == "Count: 42"


def test_render_template_no_placeholders() -> None:
    assert render_template("Hello world", {"x": "y"}) == "Hello world"


# ---- _resolve_timezone ----

def test_resolve_timezone_prefers_patient_timezone() -> None:
    patient = MagicMock()
    patient.last_known_timezone = "America/Los_Angeles"
    tz = _resolve_timezone(patient, clinic_timezone="America/Chicago")
    assert tz == zoneinfo.ZoneInfo("America/Los_Angeles")


def test_resolve_timezone_falls_back_to_clinic_when_patient_missing() -> None:
    patient = MagicMock(spec=[])  # No last_known_timezone attribute
    tz = _resolve_timezone(patient, clinic_timezone="America/Chicago")
    assert tz == zoneinfo.ZoneInfo("America/Chicago")


def test_resolve_timezone_defaults_to_eastern() -> None:
    patient = MagicMock(spec=[])
    tz = _resolve_timezone(patient, clinic_timezone="")
    assert tz == zoneinfo.ZoneInfo("America/New_York")


def test_resolve_timezone_skips_invalid_strings() -> None:
    patient = MagicMock()
    patient.last_known_timezone = "Not/A/Real/Zone"
    tz = _resolve_timezone(patient, clinic_timezone="America/Chicago")
    assert tz == zoneinfo.ZoneInfo("America/Chicago")


# ---- preferredSchedulingTimezone ----
#
# The field the practice actually maintains. A customer reported messages
# "normalized to EST" because the resolver read last_known_timezone, which holds
# a value on five rows fleet-wide, while their chart preference was set on
# 140,028 patients of whom 52,382 are not Eastern.


def _setting(name, value):
    s = MagicMock()
    s.name = name
    s.value = value
    return s


def _patient_with(settings=None, last_known=None):
    patient = MagicMock()
    patient.settings.all.return_value = settings or []
    patient.last_known_timezone = last_known
    patient.addresses.all.return_value = []
    return patient


def test_the_chart_preference_wins() -> None:
    patient = _patient_with(
        [_setting("preferredSchedulingTimezone", "America/Chicago")]
    )
    assert resolve_timezone_name(patient, "America/New_York") == "America/Chicago"


def test_the_chart_preference_beats_last_known_timezone() -> None:
    """Staff chose the preference; last_known is observed, and is set by a FHIR
    extension rather than by anyone looking at the chart."""
    patient = _patient_with(
        [_setting("preferredSchedulingTimezone", "America/Chicago")],
        last_known="America/Los_Angeles",
    )
    assert resolve_timezone_name(patient, "America/New_York") == "America/Chicago"


def test_falls_back_to_last_known_when_no_preference_is_set() -> None:
    patient = _patient_with([], last_known="America/Los_Angeles")
    assert resolve_timezone_name(patient, "America/New_York") == "America/Los_Angeles"


def test_other_settings_are_ignored() -> None:
    """The store is shared: pharmacy, lab and contactMethod live beside it."""
    patient = _patient_with([
        _setting("pharmacy", [{"pharmacy_name": "X"}]),
        _setting("contactMethod", "phone"),
        _setting("preferredSchedulingTimezone", "America/Denver"),
    ])
    assert resolve_timezone_name(patient, "America/New_York") == "America/Denver"


def test_a_non_string_preference_does_not_raise() -> None:
    """It is a JSONField, so nothing at the database level guarantees a string,
    and ZoneInfo raises TypeError rather than the ValueError the loop catches."""
    for junk in ({"zone": "America/Chicago"}, ["America/Chicago"], 42, None):
        patient = _patient_with([_setting("preferredSchedulingTimezone", junk)])
        assert resolve_timezone_name(patient, "America/New_York") == "America/New_York"


def test_an_unparseable_preference_falls_through() -> None:
    patient = _patient_with(
        [_setting("preferredSchedulingTimezone", "Not/A/Zone")],
        last_known="America/Los_Angeles",
    )
    assert resolve_timezone_name(patient, "America/New_York") == "America/Los_Angeles"


def test_zones_no_address_can_produce_still_resolve() -> None:
    """Real values from one production instance. None of these is in
    RESOLVABLE_ZONES, the eleven zones a US mailing address maps to, so the
    address heuristic could never have produced them."""
    for zone in (
        "America/Detroit",
        "America/Indiana/Indianapolis",
        "America/Kentucky/Louisville",
        "America/Menominee",
        "America/Indianapolis",          # deprecated alias, still in use
    ):
        patient = _patient_with([_setting("preferredSchedulingTimezone", zone)])
        assert resolve_timezone_name(patient, "America/New_York") == zone


def test_the_preference_read_uses_the_prefetch_cache() -> None:
    """The N+1 guard.

    Django serves a prefetch cache for `.all()` alone. A filtered `.get()` or
    `.filter()` re-queries even when `settings` was prefetched, which inside the
    reminder cron is one query per patient across the whole scan window.
    `Patient.get_setting()` is exactly that shape, so this path must not call it
    either. Same reason `telecom` and `addresses` are filtered in Python.
    """
    patient = _patient_with(
        [_setting("preferredSchedulingTimezone", "America/Chicago")]
    )
    assert resolve_timezone_name(patient, "America/New_York") == "America/Chicago"

    patient.settings.all.assert_called()
    patient.settings.get.assert_not_called()
    patient.settings.filter.assert_not_called()
    patient.get_setting.assert_not_called()


def test_a_patient_without_settings_does_not_raise() -> None:
    patient = MagicMock(spec=["last_known_timezone", "addresses"])
    patient.last_known_timezone = None
    patient.addresses.all.return_value = []
    assert resolve_timezone_name(patient, "America/Chicago") == "America/Chicago"


# ---- _tz_abbrev ----

def test_tz_abbrev_shortens_us_eastern() -> None:
    dt = datetime(2026, 1, 15, 12, 0, tzinfo=zoneinfo.ZoneInfo("America/New_York"))
    assert _tz_abbrev(dt) == "ET"


def test_tz_abbrev_shortens_us_pacific_summer() -> None:
    dt = datetime(2026, 7, 15, 12, 0, tzinfo=zoneinfo.ZoneInfo("America/Los_Angeles"))
    assert _tz_abbrev(dt) == "PT"


def test_tz_abbrev_passes_through_unknown_zones() -> None:
    dt = datetime(2026, 7, 15, 12, 0, tzinfo=zoneinfo.ZoneInfo("Europe/London"))
    # London returns BST or GMT — neither is in the shortening map
    abbrev = _tz_abbrev(dt)
    assert abbrev in {"BST", "GMT"}



def test_phone_numbers_render_formatted_for_patients() -> None:
    """Contact points store bare digits, so "Call 8005550199" reached patients."""
    from appointment_reminders.services.templates import _format_phone

    assert _format_phone("8005550199") == "(800) 555-0199"
    assert _format_phone("18005550199") == "(800) 555-0199"
    assert _format_phone("+18005550199") == "(800) 555-0199"
    assert _format_phone("(800) 555-0199") == "(800) 555-0199"
    assert _format_phone("800-555-0199") == "(800) 555-0199"


def test_phone_formatting_leaves_anything_unrecognised_alone() -> None:
    """Better an unformatted number than a mangled international one."""
    from appointment_reminders.services.templates import _format_phone

    assert _format_phone("+442071234567") == "+442071234567"
    assert _format_phone("") == ""
    assert _format_phone("ext 402") == "ext 402"


# ---- _resolve_timezone: the patient's address ----
#
# `last_known_timezone` is NULL on effectively every patient in the fleet, so
# before the address step every message rendered in the one configured clinic
# zone. These cover the step that actually resolves.

def test_resolve_timezone_uses_the_patient_address_when_no_explicit_zone() -> None:
    patient = _patient_with_addresses(_address("WA", "98101"))
    tz = _resolve_timezone(patient, clinic_timezone="America/New_York")
    assert tz == zoneinfo.ZoneInfo("America/Los_Angeles")


def test_explicit_patient_timezone_still_beats_the_address() -> None:
    """A zone set through the FHIR tz-code extension is a deliberate statement
    about where the patient is, and outranks an address that may be stale."""
    patient = _patient_with_addresses(
        _address("WA", "98101"), last_known_timezone="America/Denver"
    )
    tz = _resolve_timezone(patient, clinic_timezone="America/New_York")
    assert tz == zoneinfo.ZoneInfo("America/Denver")


def test_resolve_timezone_falls_back_to_clinic_for_an_unresolvable_address() -> None:
    patient = _patient_with_addresses(_address("ON", "M5H 2N2", country="Canada"))
    tz = _resolve_timezone(patient, clinic_timezone="America/Chicago")
    assert tz == zoneinfo.ZoneInfo("America/Chicago")


def test_resolve_timezone_falls_back_to_clinic_when_there_are_no_addresses() -> None:
    patient = _patient_with_addresses()
    tz = _resolve_timezone(patient, clinic_timezone="America/Chicago")
    assert tz == zoneinfo.ZoneInfo("America/Chicago")


def test_resolve_timezone_prefers_an_active_home_address() -> None:
    """A patient with a work address in another state is still at home when the
    reminder lands."""
    patient = _patient_with_addresses(
        _address("NY", "10001", use="work"),
        _address("CA", "94105", use="home"),
    )
    assert _resolve_timezone(patient) == zoneinfo.ZoneInfo("America/Los_Angeles")


def test_resolve_timezone_skips_an_inactive_address_for_an_active_one() -> None:
    patient = _patient_with_addresses(
        _address("NY", "10001", state="inactive"),
        _address("CA", "94105", use="work"),
    )
    assert _resolve_timezone(patient) == zoneinfo.ZoneInfo("America/Los_Angeles")


def test_resolve_timezone_uses_an_inactive_address_rather_than_nothing() -> None:
    """An address marked inactive is weak evidence, but it beats defaulting a
    Pacific patient onto Eastern."""
    patient = _patient_with_addresses(_address("CA", "94105", state="inactive"))
    assert _resolve_timezone(patient) == zoneinfo.ZoneInfo("America/Los_Angeles")


def test_resolve_timezone_ignores_a_non_string_explicit_zone() -> None:
    """`last_known_timezone` is free text; a non-string would raise a TypeError
    that the ZoneInfo guard does not catch."""
    patient = _patient_with_addresses(_address("WA", "98101"), last_known_timezone=17)
    assert _resolve_timezone(patient) == zoneinfo.ZoneInfo("America/Los_Angeles")


def test_resolve_timezone_ignores_a_garbage_explicit_zone_and_uses_the_address() -> None:
    patient = _patient_with_addresses(
        _address("WA", "98101"), last_known_timezone="Not/A/Real/Zone"
    )
    assert _resolve_timezone(patient) == zoneinfo.ZoneInfo("America/Los_Angeles")
