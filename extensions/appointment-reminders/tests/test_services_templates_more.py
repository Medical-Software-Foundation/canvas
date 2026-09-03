"""More tests for services/templates.py — covering the appointment- and
org-variable code paths that touch the ORM. Patient/Appointment/Organization
are mocked entirely; we never touch the DB.
"""

from __future__ import annotations

import json
import zoneinfo
from datetime import datetime
from unittest.mock import MagicMock, patch

from appointment_reminders.services.templates import (
    _ORG_VARS_CACHE_KEY,
    _get_org_variables,
    get_note_template_variables,
    get_template_variables,
    unresolved_placeholders,
)


def _make_telecom_qs(rows: list[MagicMock]) -> MagicMock:
    """Build a Django queryset mock that supports filter().order_by().first()."""
    qs = MagicMock()
    qs.filter.return_value = qs
    qs.order_by.return_value = qs
    qs.first.return_value = rows[0] if rows else None
    return qs


def _addr(line1="123 Main St", line2="", city="Austin", state="TX", postal="78701") -> MagicMock:
    a = MagicMock()
    a.line1 = line1
    a.line2 = line2
    a.city = city
    a.state_code = state
    a.postal_code = postal
    return a


def _addr_qs(addr=None, work_match=False) -> MagicMock:
    """Address queryset supporting BOTH `.filter()` (org path, unchanged) and
    `.all()` (location path, now filtered in Python)."""
    qs = MagicMock()

    def filter_side_effect(**kwargs):
        result = MagicMock()
        # First call has use="work" and state="active"
        if kwargs.get("use") == "work" and kwargs.get("state") == "active":
            result.first.return_value = addr if work_match else None
        else:
            result.first.return_value = addr
        return result

    qs.filter.side_effect = filter_side_effect
    # .all() rows for the in-Python location filter: set use/state so the same
    # address is selected (work-active when work_match, else state-active only).
    rows = []
    if addr is not None:
        addr.use = "work" if work_match else "home"
        addr.state = "active"
        rows = [addr]
    qs.all.return_value = rows
    return qs


def _phone_qs(phone_value=None) -> MagicMock:
    qs = MagicMock()
    qs.filter.return_value = qs
    qs.order_by.return_value = qs
    row = MagicMock(value=phone_value) if phone_value else None
    qs.first.return_value = row
    rows = []
    if row is not None:
        row.system = "phone"
        row.use = "work"
        row.state = "active"
        row.rank = 0
        rows = [row]
    qs.all.return_value = rows
    return qs


# ---- get_template_variables ----

def test_get_template_variables_full_appointment(monkeypatch) -> None:
    """Provider, location with address+phone, telehealth link via meeting_link."""
    monkeypatch.setattr(
        "appointment_reminders.services.templates._get_org_variables",
        lambda: {
            "organization_full_name": "TestOrg",
            "organization_short_name": "TO",
            "organization_address": "1 St",
            "organization_phone": "555-1111",
        },
    )

    patient = MagicMock()
    patient.first_name = "Jane"
    patient.last_name = "Doe"
    patient.preferred_first_name = "Janie"
    patient.last_known_timezone = "America/New_York"

    role = MagicMock()
    role.public_abbreviation = "MD"
    provider = MagicMock()
    provider.first_name = "Sam"
    provider.last_name = "Park"
    provider.roles.all.return_value = [role]
    # No personal_meeting_room_link

    location = MagicMock()
    location.full_name = "Main Clinic"
    location.short_name = "Main"
    location.addresses = _addr_qs(
        addr=_addr(line1="100 A St", line2="Suite 5", city="Austin", state="TX", postal="78701"),
        work_match=True,
    )
    location.telecom = _phone_qs(phone_value="+15555550000")

    appointment = MagicMock()
    appointment.start_time = datetime(2026, 6, 1, 14, 30, tzinfo=zoneinfo.ZoneInfo("UTC"))
    appointment.provider = provider
    appointment.location = location
    appointment.description = "Follow-up"
    appointment.meeting_link = "https://meet.example.com/abc"

    result = get_template_variables(patient, appointment, clinic_timezone="America/Chicago")

    assert result["patient_first_name"] == "Jane"
    assert result["patient_full_name"] == "Jane Doe"
    assert result["provider_name"] == "Sam Park"
    assert result["credentials"] == "MD"
    assert result["location_name"] == "Main Clinic"
    assert result["location_full_name"] == "Main Clinic"
    assert result["location_short_name"] == "Main"
    assert "100 A St" in result["location_address"]
    assert "Suite 5" in result["location_address"]
    assert "Austin, TX 78701" in result["location_address"]
    assert result["location_phone"] == "(555) 555-0000"  # formatted for the patient
    assert result["telehealth_link"] == "https://meet.example.com/abc"
    assert result["appointment_type"] == "Follow-up"
    assert result["organization_full_name"] == "TestOrg"


def test_get_template_variables_falls_back_to_provider_meeting_room(monkeypatch) -> None:
    monkeypatch.setattr(
        "appointment_reminders.services.templates._get_org_variables",
        lambda: {"organization_full_name": "", "organization_short_name": "",
                 "organization_address": "", "organization_phone": ""},
    )
    patient = MagicMock(spec=[])
    patient.first_name = "Jane"
    patient.last_name = "Doe"
    patient.preferred_first_name = ""

    provider = MagicMock()
    provider.first_name = "Sam"
    provider.last_name = "Park"
    provider.roles.all.return_value = []
    provider.personal_meeting_room_link = "https://meet.example.com/sam"

    appointment = MagicMock(spec=[
        "start_time", "provider", "location", "description"
    ])
    appointment.start_time = datetime(2026, 6, 1, 14, 30, tzinfo=zoneinfo.ZoneInfo("UTC"))
    appointment.provider = provider
    appointment.location = None
    appointment.description = ""

    result = get_template_variables(patient, appointment)
    assert result["telehealth_link"] == "https://meet.example.com/sam"
    assert result["location_name"] == "our clinic"
    assert result["location_full_name"] == "our clinic"
    assert result["credentials"] == ""


def test_get_template_variables_handles_missing_provider_and_location(monkeypatch) -> None:
    monkeypatch.setattr(
        "appointment_reminders.services.templates._get_org_variables",
        lambda: {"organization_full_name": "", "organization_short_name": "",
                 "organization_address": "", "organization_phone": ""},
    )
    patient = MagicMock(spec=[])
    patient.first_name = "Jane"
    patient.last_name = "Doe"
    patient.preferred_first_name = ""

    appointment = MagicMock(spec=["start_time", "provider", "location", "description"])
    appointment.start_time = datetime(2026, 6, 1, 14, 30, tzinfo=zoneinfo.ZoneInfo("UTC"))
    appointment.provider = None
    appointment.location = None
    appointment.description = None

    result = get_template_variables(patient, appointment)
    assert result["provider_name"] == "your provider"
    assert result["location_name"] == "our clinic"
    assert result["telehealth_link"] == ""
    assert result["appointment_type"] == ""


def test_get_template_variables_provider_roles_exception_handled(monkeypatch) -> None:
    """A failure iterating provider.roles must not break template generation."""
    monkeypatch.setattr(
        "appointment_reminders.services.templates._get_org_variables",
        lambda: {"organization_full_name": "", "organization_short_name": "",
                 "organization_address": "", "organization_phone": ""},
    )
    patient = MagicMock(spec=[])
    patient.first_name = "Jane"
    patient.last_name = "Doe"
    patient.preferred_first_name = ""

    provider = MagicMock()
    provider.first_name = "Sam"
    provider.last_name = "Park"
    provider.roles.all.side_effect = RuntimeError("DB blew up")

    appointment = MagicMock(spec=["start_time", "provider", "location", "description"])
    appointment.start_time = datetime(2026, 6, 1, 14, 30, tzinfo=zoneinfo.ZoneInfo("UTC"))
    appointment.provider = provider
    appointment.location = None
    appointment.description = ""

    result = get_template_variables(patient, appointment)
    assert result["provider_name"] == "Sam Park"
    assert result["credentials"] == ""


def test_get_template_variables_location_address_falls_back_to_state_active(monkeypatch) -> None:
    """When no work address, the code falls back to state=active."""
    monkeypatch.setattr(
        "appointment_reminders.services.templates._get_org_variables",
        lambda: {"organization_full_name": "", "organization_short_name": "",
                 "organization_address": "", "organization_phone": ""},
    )
    patient = MagicMock(spec=[])
    patient.first_name = "Jane"
    patient.last_name = "Doe"
    patient.preferred_first_name = ""

    location = MagicMock()
    location.full_name = "Main Clinic"
    location.short_name = ""
    # A state-active address that is NOT use="work" — exercises the fallback.
    addr = _addr(line1="100 A St", city="Austin", state="TX", postal="78701")
    addr.use = "home"
    addr.state = "active"
    addresses_qs = MagicMock()
    addresses_qs.all.return_value = [addr]
    location.addresses = addresses_qs
    # No phone at all
    telecom_qs = MagicMock()
    telecom_qs.all.return_value = []
    location.telecom = telecom_qs

    appointment = MagicMock(spec=["start_time", "provider", "location", "description"])
    appointment.start_time = datetime(2026, 6, 1, 14, 30, tzinfo=zoneinfo.ZoneInfo("UTC"))
    appointment.provider = None
    appointment.location = location
    appointment.description = ""

    result = get_template_variables(patient, appointment)
    assert "100 A St" in result["location_address"]
    assert result["location_phone"] == ""


# ---- _get_org_variables ----

def test_get_org_variables_uses_cache_when_available() -> None:
    cached = {
        "organization_full_name": "Cached Org",
        "organization_short_name": "CO",
        "organization_address": "100 X",
        "organization_phone": "555",
    }
    with patch("appointment_reminders.services.templates.get_cache") as mock_cache:
        mock_cache.return_value.get.return_value = json.dumps(cached)
        result = _get_org_variables()
    assert result == cached
    mock_cache.return_value.get.assert_called_once_with(_ORG_VARS_CACHE_KEY)


def test_get_org_variables_recomputes_when_cache_miss() -> None:
    """Cache empty → query Organization, then write to cache."""
    org = MagicMock()
    org.full_name = "Real Org"
    org.short_name = "RO"
    org.addresses = _addr_qs(
        addr=_addr(line1="500 Main", city="Austin", state="TX", postal="78702"),
        work_match=True,
    )
    org.telecom = _phone_qs(phone_value="+15555551111")

    with patch(
        "appointment_reminders.services.templates.get_cache"
    ) as mock_cache, patch(
        "appointment_reminders.services.templates.Organization"
    ) as mock_org_cls:
        mock_cache.return_value.get.return_value = None
        mock_org_cls.objects.first.return_value = org
        result = _get_org_variables()

    assert result["organization_full_name"] == "Real Org"
    assert result["organization_short_name"] == "RO"
    assert "500 Main" in result["organization_address"]
    assert result["organization_phone"] == "(555) 555-1111"  # formatted for the patient
    mock_cache.return_value.set.assert_called_once()


def test_get_org_variables_handles_corrupt_cache_payload() -> None:
    """A non-JSON cache value triggers fallback to live query."""
    org = MagicMock()
    org.full_name = "Real"
    org.short_name = ""
    org.addresses = _addr_qs(work_match=False)
    org.telecom = _phone_qs(phone_value=None)
    with patch(
        "appointment_reminders.services.templates.get_cache"
    ) as mock_cache, patch(
        "appointment_reminders.services.templates.Organization"
    ) as mock_org_cls:
        mock_cache.return_value.get.return_value = "not-json-{"
        mock_org_cls.objects.first.return_value = org
        result = _get_org_variables()
    assert result["organization_full_name"] == "Real"


def test_get_org_variables_handles_no_organization_record() -> None:
    with patch(
        "appointment_reminders.services.templates.get_cache"
    ) as mock_cache, patch(
        "appointment_reminders.services.templates.Organization"
    ) as mock_org_cls:
        mock_cache.return_value.get.return_value = None
        mock_org_cls.objects.first.return_value = None
        result = _get_org_variables()
    assert result == {
        "organization_full_name": "",
        "organization_short_name": "",
        "organization_address": "",
        "organization_phone": "",
    }


def test_get_org_variables_handles_db_exception() -> None:
    """A DB exception falls back to empty strings without raising."""
    with patch(
        "appointment_reminders.services.templates.get_cache"
    ) as mock_cache, patch(
        "appointment_reminders.services.templates.Organization"
    ) as mock_org_cls:
        mock_cache.return_value.get.return_value = None
        mock_org_cls.objects.first.side_effect = RuntimeError("DB down")
        result = _get_org_variables()
    assert result["organization_full_name"] == ""


def test_get_org_variables_swallows_cache_set_exception() -> None:
    """If cache.set throws, _get_org_variables still returns the computed values."""
    org = MagicMock()
    org.full_name = "Real"
    org.short_name = ""
    org.addresses = _addr_qs(work_match=False)
    org.telecom = _phone_qs(phone_value=None)
    with patch(
        "appointment_reminders.services.templates.get_cache"
    ) as mock_cache, patch(
        "appointment_reminders.services.templates.Organization"
    ) as mock_org_cls:
        mock_cache.return_value.get.return_value = None
        mock_cache.return_value.set.side_effect = RuntimeError("cache down")
        mock_org_cls.objects.first.return_value = org
        result = _get_org_variables()
    assert result["organization_full_name"] == "Real"




# ---- date / time formatting ----

def test_appointment_date_and_time_are_not_zero_padded(monkeypatch) -> None:
    """Native Canvas copy reads '3:40 PM', so ours should too. `%I`/`%d` would
    render '03:40 PM' and 'August 05, 2026'.
    """
    monkeypatch.setattr(
        "appointment_reminders.services.templates._get_org_variables", lambda: {}
    )

    patient = MagicMock()
    patient.first_name = "Jane"
    patient.last_name = "Doe"
    patient.last_known_timezone = "America/New_York"

    appointment = MagicMock()
    # 19:40 UTC on Aug 5 == 3:40 PM EDT
    appointment.start_time = datetime(2026, 8, 5, 19, 40, tzinfo=zoneinfo.ZoneInfo("UTC"))
    appointment.provider = None
    appointment.location = None
    appointment.description = ""
    appointment.meeting_link = ""

    result = get_template_variables(patient, appointment)

    assert result["appointment_date"] == "August 5, 2026"
    assert result["appointment_time"] == "3:40 PM ET"


def test_appointment_time_renders_noon_and_midnight_as_twelve(monkeypatch) -> None:
    """`hour % 12` alone would render noon as '0:00 PM'."""
    monkeypatch.setattr(
        "appointment_reminders.services.templates._get_org_variables", lambda: {}
    )

    patient = MagicMock()
    patient.first_name = "Jane"
    patient.last_name = "Doe"
    patient.last_known_timezone = "UTC"

    appointment = MagicMock()
    appointment.provider = None
    appointment.location = None
    appointment.description = ""
    appointment.meeting_link = ""

    appointment.start_time = datetime(2026, 8, 5, 12, 0, tzinfo=zoneinfo.ZoneInfo("UTC"))
    assert get_template_variables(patient, appointment)["appointment_time"].startswith("12:00 PM")

    appointment.start_time = datetime(2026, 8, 5, 0, 0, tzinfo=zoneinfo.ZoneInfo("UTC"))
    assert get_template_variables(patient, appointment)["appointment_time"].startswith("12:00 AM")


# ---- get_note_template_variables ----

def test_note_variables_fill_telehealth_link_and_attribution(monkeypatch) -> None:
    """The bug this guards: a standalone-note telehealth send used to build a
    9-key dict, leaving {{telehealth_link}} and {{business_line_attribution}}
    literal in the delivered SMS, and rendering the time in raw UTC.
    """
    monkeypatch.setattr(
        "appointment_reminders.services.templates._get_org_variables", lambda: {}
    )
    monkeypatch.setattr(
        "appointment_reminders.services.templates.get_business_line_name",
        lambda patient: "Northwind Health",
    )
    monkeypatch.setattr(
        "appointment_reminders.services.templates.resolve_attribution",
        lambda config, name: "Northwind Health",
    )

    patient = MagicMock()
    patient.first_name = "Jane"
    patient.last_name = "Doe"
    patient.last_known_timezone = "America/New_York"

    provider = MagicMock()
    provider.first_name = "Sam"
    provider.last_name = "Park"
    provider.roles.all.return_value = []
    provider.personal_meeting_room_link = "https://meet.example.com/sam"

    note = MagicMock()
    note.datetime_of_service = datetime(2026, 8, 5, 19, 40, tzinfo=zoneinfo.ZoneInfo("UTC"))
    note.provider = provider
    note.location = None
    note.title = "Telehealth Visit"

    result = get_note_template_variables(patient, note, config=object())

    # The two that used to render as literal template syntax
    assert result["telehealth_link"] == "https://meet.example.com/sam"
    assert result["business_line_attribution"] == "Northwind Health"
    # Local time with a zone label, not raw UTC ("7:40 PM" with no label)
    assert result["appointment_time"] == "3:40 PM ET"
    assert result["appointment_date"] == "August 5, 2026"
    assert result["appointment_type"] == "Telehealth Visit"
    assert result["provider_name"] == "Sam Park"


def test_note_variables_cover_every_appointment_placeholder(monkeypatch) -> None:
    """Notes and appointments must expose the same key set, or a template that
    renders correctly for one silently breaks for the other.
    """
    monkeypatch.setattr(
        "appointment_reminders.services.templates._get_org_variables", lambda: {}
    )

    patient = MagicMock()
    patient.first_name = "Jane"
    patient.last_name = "Doe"
    patient.last_known_timezone = "UTC"

    appointment = MagicMock()
    appointment.start_time = datetime(2026, 8, 5, 19, 40, tzinfo=zoneinfo.ZoneInfo("UTC"))
    appointment.provider = None
    appointment.location = None
    appointment.description = ""
    appointment.meeting_link = ""

    note = MagicMock()
    note.datetime_of_service = appointment.start_time
    note.provider = None
    note.location = None
    note.title = ""

    appt_keys = set(get_template_variables(patient, appointment).keys())
    note_keys = set(get_note_template_variables(patient, note).keys())
    assert note_keys == appt_keys


def test_note_variables_tolerate_missing_service_datetime(monkeypatch) -> None:
    """A note with no datetime_of_service must render empty date/time, not raise."""
    monkeypatch.setattr(
        "appointment_reminders.services.templates._get_org_variables", lambda: {}
    )

    patient = MagicMock()
    patient.first_name = "Jane"
    patient.last_name = "Doe"
    patient.last_known_timezone = "UTC"

    note = MagicMock()
    note.datetime_of_service = None
    note.provider = None
    note.location = None
    note.title = "Phone call"

    result = get_note_template_variables(patient, note)

    assert result["appointment_date"] == ""
    assert result["appointment_time"] == ""
    assert result["appointment_type"] == "Phone call"


# ---- unresolved_placeholders ----

def test_unresolved_placeholders_finds_names_and_dedupes() -> None:
    text = "Join {{telehealth_link}} for {{telehealth_link}} and {{business_line_attribution}}"
    assert unresolved_placeholders(text) == [
        "telehealth_link",
        "business_line_attribution",
    ]


def test_unresolved_placeholders_empty_for_fully_rendered_text() -> None:
    assert unresolved_placeholders("Hi Jane, your visit is August 5, 2026.") == []
    assert unresolved_placeholders("") == []


def test_unresolved_placeholders_ignores_unterminated_braces() -> None:
    """An unclosed '{{' is not a placeholder and must not loop forever."""
    assert unresolved_placeholders("literal {{ braces with no close") == []


# ---- end to end: the rendered time follows the patient, not the clinic ----

def test_appointment_time_renders_in_the_patients_own_zone(monkeypatch) -> None:
    """The whole point of the change: a Seattle patient booked by an Eastern
    clinic reads 12:40 PM PT, not 3:40 PM ET."""
    monkeypatch.setattr(
        "appointment_reminders.services.templates._get_org_variables", lambda: {}
    )

    address = MagicMock()
    address.state_code = "WA"
    address.postal_code = "98101"
    address.country = "US"
    address.use = "home"
    address.state = "active"

    patient = MagicMock()
    patient.first_name = "Jane"
    patient.last_name = "Doe"
    patient.preferred_first_name = "Janie"
    patient.last_known_timezone = None
    patient.addresses.all.return_value = [address]

    appointment = MagicMock()
    appointment.start_time = datetime(2026, 8, 5, 19, 40, tzinfo=zoneinfo.ZoneInfo("UTC"))
    appointment.provider = None
    appointment.location = None
    appointment.description = "Follow-up"
    appointment.meeting_link = ""

    result = get_template_variables(
        patient, appointment, clinic_timezone="America/New_York"
    )

    assert result["appointment_time"] == "12:40 PM PT"
    assert result["appointment_date"] == "August 5, 2026"


def test_appointment_time_falls_back_to_the_clinic_zone_without_an_address(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "appointment_reminders.services.templates._get_org_variables", lambda: {}
    )

    patient = MagicMock()
    patient.first_name = "Jane"
    patient.last_name = "Doe"
    patient.preferred_first_name = "Janie"
    patient.last_known_timezone = None
    patient.addresses.all.return_value = []

    appointment = MagicMock()
    appointment.start_time = datetime(2026, 8, 5, 19, 40, tzinfo=zoneinfo.ZoneInfo("UTC"))
    appointment.provider = None
    appointment.location = None
    appointment.description = "Follow-up"
    appointment.meeting_link = ""

    result = get_template_variables(
        patient, appointment, clinic_timezone="America/New_York"
    )

    assert result["appointment_time"] == "3:40 PM ET"
