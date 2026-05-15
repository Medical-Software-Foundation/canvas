"""Tests for api/calendar.py."""

from unittest.mock import MagicMock, patch

from provider_availability_manager.api.calendar import CalendarAPI, _json_response


def _handler(body=None):
    h = CalendarAPI.__new__(CalendarAPI)
    request = MagicMock()
    request.json.return_value = body or {}
    h.request = request
    h.secrets = {}
    return h


def test_json_response_returns_response_with_status():
    resp = _json_response({"hi": "there"}, 200)
    # Status was applied
    assert resp.status_code == 200


def test_post_returns_existing_calendar():
    h = _handler({
        "provider": "prov-1",
        "providerName": "Bob",
        "location": "loc-1",
        "locationName": "Loc",
        "type": "Clinic",
    })

    with patch(
        "provider_availability_manager.api.calendar.Calendar"
    ) as mock_cal:
        mock_cal.objects.for_calendar_name.return_value.values_list.return_value.last.return_value = "existing-id"
        result = h.post()
        assert len(result) == 1


def test_post_creates_new_calendar_clinic():
    h = _handler({
        "provider": "prov-1",
        "providerName": "Bob",
        "location": "loc-1",
        "locationName": "Loc",
        "type": "Clinic",
        "description": "desc",
    })

    with patch(
        "provider_availability_manager.api.calendar.Calendar"
    ) as mock_cal, patch(
        "provider_availability_manager.api.calendar.CalendarEffect"
    ) as mock_effect:
        mock_cal.objects.for_calendar_name.return_value.values_list.return_value.last.return_value = None
        mock_effect.return_value.create.return_value = MagicMock(name="effect")
        result = h.post()
        assert len(result) == 2  # effect + json response


def test_post_creates_new_calendar_admin():
    h = _handler({
        "provider": "prov-1",
        "providerName": "Bob",
        "type": "Admin",
    })

    with patch(
        "provider_availability_manager.api.calendar.Calendar"
    ) as mock_cal, patch(
        "provider_availability_manager.api.calendar.CalendarEffect"
    ) as mock_effect:
        mock_cal.objects.for_calendar_name.return_value.values_list.return_value.last.return_value = None
        mock_effect.return_value.create.return_value = MagicMock(name="effect")
        result = h.post()
        assert len(result) == 2


def test_post_unknown_type_defaults_to_clinic():
    h = _handler({
        "provider": "prov-1",
        "providerName": "Bob",
        "type": "OtherType",
    })

    with patch(
        "provider_availability_manager.api.calendar.Calendar"
    ) as mock_cal, patch(
        "provider_availability_manager.api.calendar.CalendarEffect"
    ) as mock_effect:
        mock_cal.objects.for_calendar_name.return_value.values_list.return_value.last.return_value = None
        mock_effect.return_value.create.return_value = MagicMock(name="effect")
        result = h.post()
        assert len(result) == 2
