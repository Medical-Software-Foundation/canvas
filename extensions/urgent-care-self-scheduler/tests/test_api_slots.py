from types import SimpleNamespace
from zoneinfo import ZoneInfo

from urgent_care_self_scheduler.handlers.api import (
    SlotsAPI,
    _parse_lead_time,
    _resolve_timezone,
)


# ---- _parse_lead_time -------------------------------------------------------


def test_parse_lead_time_empty_string_defaults_to_30() -> None:
    assert _parse_lead_time("") == 30


def test_parse_lead_time_none_defaults_to_30() -> None:
    assert _parse_lead_time(None) == 30


def test_parse_lead_time_valid_int_returned() -> None:
    assert _parse_lead_time("60") == 60


def test_parse_lead_time_zero_allowed() -> None:
    assert _parse_lead_time("0") == 0


def test_parse_lead_time_negative_falls_back_to_default() -> None:
    assert _parse_lead_time("-5") == 30


def test_parse_lead_time_garbage_falls_back_to_default() -> None:
    assert _parse_lead_time("not a number") == 30


# ---- _resolve_timezone ------------------------------------------------------


def test_resolve_timezone_returns_zoneinfo_for_valid_iana_string() -> None:
    tz = _resolve_timezone("America/New_York")
    assert isinstance(tz, ZoneInfo)
    assert str(tz) == "America/New_York"


def test_resolve_timezone_falls_back_to_utc_for_empty() -> None:
    assert _resolve_timezone(None) == ZoneInfo("UTC")
    assert _resolve_timezone("") == ZoneInfo("UTC")


def test_resolve_timezone_falls_back_to_utc_for_invalid() -> None:
    assert _resolve_timezone("Not/A_Real_TZ") == ZoneInfo("UTC")


# ---- SlotsAPI ---------------------------------------------------------------


def test_slots_api_path() -> None:
    assert SlotsAPI.PATH == "/api/slots"


def test_slots_api_authenticate_accepts_patient() -> None:
    api = SlotsAPI.__new__(SlotsAPI)
    creds = SimpleNamespace(logged_in_user={"id": "p-1", "type": "Patient"})
    assert api.authenticate(creds) is True


def test_slots_api_authenticate_rejects_staff() -> None:
    import pytest
    from canvas_sdk.handlers.simple_api.security import InvalidCredentialsError

    api = SlotsAPI.__new__(SlotsAPI)
    creds = SimpleNamespace(logged_in_user={"id": "s-1", "type": "Staff"})
    with pytest.raises(InvalidCredentialsError):
        api.authenticate(creds)


def test_slots_api_returns_503_when_note_type_secret_missing() -> None:
    import json

    api = SlotsAPI.__new__(SlotsAPI)
    api.secrets = {}  # type: ignore[attr-defined]
    response = api.get()
    assert len(response) == 1
    res = response[0]
    assert res.status_code == 503
    body = json.loads(res.content) if hasattr(res, "content") else res.body
    assert "error" in body


def test_slots_api_returns_503_when_note_type_secret_blank() -> None:
    api = SlotsAPI.__new__(SlotsAPI)
    api.secrets = {"URGENT_CARE_NOTE_TYPE_NAME": "   "}  # type: ignore[attr-defined]
    response = api.get()
    assert response[0].status_code == 503


def test_slots_api_happy_path_returns_slots_and_fallback_phone(mocker) -> None:
    import json as _json

    fake_slots = [
        {"provider_id": "p1", "provider_name": "Dr. X", "start_iso": "2026-05-01T08:00:00+00:00",
         "end_iso": "2026-05-01T08:15:00+00:00"},
    ]
    find_mock = mocker.patch(
        "urgent_care_self_scheduler.handlers.api.find_available_slots",
        return_value=fake_slots,
    )
    mocker.patch(
        "urgent_care_self_scheduler.handlers.api._practice_timezone",
        return_value=ZoneInfo("America/New_York"),
    )

    api = SlotsAPI.__new__(SlotsAPI)
    api.secrets = {  # type: ignore[attr-defined]
        "URGENT_CARE_NOTE_TYPE_NAME": "Urgent Care",
        "URGENT_CARE_LEAD_TIME_MINUTES": "60",
        "URGENT_CARE_FALLBACK_PHONE": "555-867-5309",
    }
    api.request = SimpleNamespace(headers={})  # type: ignore[attr-defined]
    response = api.get()
    assert len(response) == 1
    body = _json.loads(response[0].content)
    assert body["slots"] == fake_slots
    assert body["fallback_phone"] == "555-867-5309"
    # No patient in session here → no existing-visit check performed.
    assert body["existing_urgent_care_visit"] is False
    # Modality is surfaced so the wizard knows whether to label slots by location;
    # unset secret defaults to telehealth.
    assert body["modality"] == "telehealth"

    # Verify the slot search was called with the parsed lead time and the
    # configured note-type name; window spans now → now + 3 days.
    assert find_mock.call_count == 1
    kwargs = find_mock.call_args.kwargs
    assert kwargs["note_type_name"] == "Urgent Care"
    assert kwargs["lead_time_minutes"] == 60
    assert str(kwargs["practice_timezone"]) == "America/New_York"


def test_slots_api_uses_default_lead_time_when_secret_unset(mocker) -> None:
    find_mock = mocker.patch(
        "urgent_care_self_scheduler.handlers.api.find_available_slots",
        return_value=[],
    )
    mocker.patch(
        "urgent_care_self_scheduler.handlers.api._practice_timezone",
        return_value=ZoneInfo("UTC"),
    )

    api = SlotsAPI.__new__(SlotsAPI)
    api.secrets = {"URGENT_CARE_NOTE_TYPE_NAME": "Urgent Care"}  # type: ignore[attr-defined]
    api.request = SimpleNamespace(headers={})  # type: ignore[attr-defined]
    api.get()
    assert find_mock.call_args.kwargs["lead_time_minutes"] == 30


def test_slots_api_empty_response_includes_empty_fallback_phone(mocker) -> None:
    import json as _json

    mocker.patch(
        "urgent_care_self_scheduler.handlers.api.find_available_slots",
        return_value=[],
    )
    mocker.patch(
        "urgent_care_self_scheduler.handlers.api._practice_timezone",
        return_value=ZoneInfo("UTC"),
    )

    api = SlotsAPI.__new__(SlotsAPI)
    api.secrets = {"URGENT_CARE_NOTE_TYPE_NAME": "Urgent Care"}  # type: ignore[attr-defined]
    api.request = SimpleNamespace(headers={})  # type: ignore[attr-defined]
    response = api.get()
    body = _json.loads(response[0].content)
    assert body["slots"] == []
    assert body["fallback_phone"] == ""


def test_slots_api_reports_existing_urgent_care_visit(mocker) -> None:
    import json as _json

    mocker.patch(
        "urgent_care_self_scheduler.handlers.api.find_available_slots",
        return_value=[],
    )
    mocker.patch(
        "urgent_care_self_scheduler.handlers.api._practice_timezone",
        return_value=ZoneInfo("UTC"),
    )
    mocker.patch(
        "urgent_care_self_scheduler.handlers.api.resolve_urgent_care_note_type",
        return_value=SimpleNamespace(id="nt-1"),
    )
    visit_mock = mocker.patch(
        "urgent_care_self_scheduler.handlers.api._patient_has_upcoming_urgent_care_visit",
        return_value=True,
    )

    api = SlotsAPI.__new__(SlotsAPI)
    api.secrets = {"URGENT_CARE_NOTE_TYPE_NAME": "Urgent Care"}  # type: ignore[attr-defined]
    api.request = SimpleNamespace(headers={"canvas-logged-in-user-id": "patient-1"})  # type: ignore[attr-defined]
    response = api.get()
    body = _json.loads(response[0].content)
    assert body["existing_urgent_care_visit"] is True
    assert visit_mock.call_args.args[0] == "patient-1"
