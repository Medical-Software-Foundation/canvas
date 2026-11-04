import datetime
from datetime import UTC

import pytest
from canvas_sdk.test_utils.factories import PatientFactory
from canvas_sdk.v1.data.patient import PatientContactPoint

from public_appointment_booking import booking

NOW = datetime.datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
DOB = datetime.date(1990, 4, 1)


def _contact(patient, system: str, value: str, state: str = "active") -> None:
    PatientContactPoint.objects.create(
        patient=patient,
        system=system,
        value=value,
        use="home",
        use_notes="",
        rank=1,
        state=state,
        has_consent=False,
        verification_token="",
        opted_out=False,
    )


def _patient(**kwargs):
    defaults = {
        "first_name": "Ana",
        "last_name": "Ruiz",
        "birth_date": DOB,
        "active": True,
    }
    defaults.update(kwargs)
    return PatientFactory(**defaults)


def _match(**overrides):
    kwargs = {
        "first_name": "ana",
        "last_name": "RUIZ",
        "birth_date": DOB,
        "email": "ana@example.org",
        "phone": "5551234567",
    }
    kwargs.update(overrides)
    return booking.find_matching_patient(**kwargs)


# ---- holds ---------------------------------------------------------------------------


def test_hold_key_is_the_same_instant_across_timezones() -> None:
    eastern = datetime.timezone(datetime.timedelta(hours=-5))
    a = booking.hold_key("p1", datetime.datetime(2026, 11, 10, 10, 0, tzinfo=eastern))
    b = booking.hold_key("p1", datetime.datetime(2026, 11, 10, 15, 0, tzinfo=UTC))
    assert a == b == "hold:p1:20261110T150000Z"


def test_hold_seconds_lasts_until_an_hour_after_start() -> None:
    start = NOW + datetime.timedelta(hours=2)
    assert booking.hold_seconds(start, NOW) == 3 * 3600


def test_hold_seconds_is_capped_and_floored() -> None:
    assert (
        booking.hold_seconds(NOW + datetime.timedelta(days=30), NOW)
        == booking.MAX_CACHE_SECONDS
    )
    assert booking.hold_seconds(NOW - datetime.timedelta(days=1), NOW) == 60


def test_drop_held_removes_only_held_slots(cache) -> None:
    slots = [
        {"provider_id": "p1", "start_iso": "2026-11-10T15:00:00+00:00"},
        {"provider_id": "p1", "start_iso": "2026-11-10T15:30:00+00:00"},
        {"provider_id": "p2", "start_iso": "2026-11-10T15:00:00+00:00"},
    ]
    cache.set(
        booking.hold_key("p1", datetime.datetime(2026, 11, 10, 15, tzinfo=UTC)), "1"
    )
    assert booking.drop_held(slots, cache) == slots[1:]
    assert booking.drop_held([], cache) == []


def test_public_slot_keeps_only_public_fields() -> None:
    slot = {
        "provider_id": "p1",
        "provider_name": "Dr. Lee",
        "start_iso": "2026-11-10T15:00:00+00:00",
        "end_iso": "2026-11-10T15:30:00+00:00",
        "location_name": "Main",
        "location_id": "secret-location",
        "calendar_id": "secret-calendar",
    }
    out = booking.public_slot(slot, 30)
    assert set(out) == {*booking.PUBLIC_SLOT_FIELDS, "duration_minutes"}
    assert out["duration_minutes"] == 30


# ---- patient matching ------------------------------------------------------------------


@pytest.mark.django_db
def test_match_by_email_case_insensitive_name() -> None:
    patient = _patient()
    _contact(patient, "email", "Ana@Example.org")
    assert _match() == patient


@pytest.mark.django_db
def test_match_by_phone_last_ten_digits() -> None:
    patient = _patient()
    _contact(patient, "phone", "+1 (555) 123-4567")
    assert _match(email="other@example.org") == patient


@pytest.mark.django_db
def test_no_match_when_contact_differs() -> None:
    patient = _patient()
    _contact(patient, "email", "someone@example.org")
    _contact(patient, "phone", "5559990000")
    assert _match() is None


@pytest.mark.django_db
def test_no_match_on_wrong_birth_date_or_inactive() -> None:
    patient = _patient(birth_date=datetime.date(1991, 4, 1))
    _contact(patient, "email", "ana@example.org")
    inactive = _patient(active=False)
    _contact(inactive, "email", "ana@example.org")
    assert _match() is None


@pytest.mark.django_db
def test_deleted_contact_point_does_not_match() -> None:
    patient = _patient()
    _contact(patient, "email", "ana@example.org", state="deleted")
    assert _match() is None


@pytest.mark.django_db
def test_ambiguous_match_returns_none() -> None:
    for _ in range(2):
        _contact(_patient(), "email", "ana@example.org")
    assert _match() is None
