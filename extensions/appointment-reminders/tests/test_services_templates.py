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
)


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
