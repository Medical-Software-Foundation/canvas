"""Tests for api/calendar.py."""

from unittest.mock import MagicMock, patch

from canvas_sdk.effects.calendar import CalendarType

from drag_drop_availability.api.calendar import (
    CalendarAPI,
    _existing_calendar_id,
    _json_response,
)


def _handler(body=None):
    h = CalendarAPI.__new__(CalendarAPI)
    request = MagicMock()
    request.json.return_value = body or {}
    h.request = request
    h.secrets = {}
    return h


def _no_description_match(mock_cal):
    """Make the description-based lookup return no candidates."""
    mock_cal.objects.filter.return_value.order_by.return_value = []


def test_json_response_returns_response_with_status():
    resp = _json_response({"hi": "there"}, 200)
    # Status was applied
    assert resp.status_code == 200


def test_post_returns_existing_calendar_via_legacy_title():
    h = _handler({
        "provider": "prov-1",
        "providerName": "Bob",
        "location": "loc-1",
        "locationName": "Loc",
        "type": "Clinic",
    })

    with patch("drag_drop_availability.api.calendar.Calendar") as mock_cal:
        _no_description_match(mock_cal)
        mock_cal.objects.for_calendar_name.return_value.values_list.return_value.last.return_value = "existing-id"
        result = h.post()
        assert len(result) == 1


def test_post_returns_existing_calendar_via_description_uuid():
    # The description-UUID lookup matches even when the stored title carries a
    # credential suffix the posted providerName lacks — so no duplicate is made.
    h = _handler({
        "provider": "staff-uuid-123",
        "providerName": "John Harris",  # title says "John Harris MD"
        "location": "loc-1",
        "locationName": "Transformative Wellness",
        "type": "Admin",
    })

    existing = MagicMock()
    existing.id = "existing-admin-cal"
    existing.title = "John Harris MD: Admin: Transformative Wellness"
    existing.description = "staff-uuid-123"

    with patch("drag_drop_availability.api.calendar.Calendar") as mock_cal, patch(
        "drag_drop_availability.api.calendar.CalendarEffect"
    ) as mock_effect:
        mock_cal.objects.filter.return_value.order_by.return_value = [existing]
        result = h.post()
        # Existing calendar reused — only the JSON response, no create effect.
        assert len(result) == 1
        mock_effect.assert_not_called()
        # Legacy exact-title lookup never needed.
        mock_cal.objects.for_calendar_name.assert_not_called()


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
        "drag_drop_availability.api.calendar.Calendar"
    ) as mock_cal, patch(
        "drag_drop_availability.api.calendar.CalendarEffect"
    ) as mock_effect:
        _no_description_match(mock_cal)
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
        "drag_drop_availability.api.calendar.Calendar"
    ) as mock_cal, patch(
        "drag_drop_availability.api.calendar.CalendarEffect"
    ) as mock_effect:
        _no_description_match(mock_cal)
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
        "drag_drop_availability.api.calendar.Calendar"
    ) as mock_cal, patch(
        "drag_drop_availability.api.calendar.CalendarEffect"
    ) as mock_effect:
        _no_description_match(mock_cal)
        mock_cal.objects.for_calendar_name.return_value.values_list.return_value.last.return_value = None
        mock_effect.return_value.create.return_value = MagicMock(name="effect")
        result = h.post()
        assert len(result) == 2


# _existing_calendar_id --------------------------------------------------

def test_existing_calendar_id_no_provider_returns_none():
    assert _existing_calendar_id(None, CalendarType.Administrative, "Loc") is None


def test_existing_calendar_id_matches_on_location():
    cal_match = MagicMock()
    cal_match.id = "match"
    cal_match.title = "John Harris MD: Admin: Transformative Wellness"
    cal_other = MagicMock()
    cal_other.id = "other-loc"
    cal_other.title = "John Harris MD: Admin: Some Other Clinic"

    with patch("drag_drop_availability.api.calendar.Calendar") as mock_cal:
        mock_cal.objects.filter.return_value.order_by.return_value = [cal_other, cal_match]
        result = _existing_calendar_id(
            "staff-uuid", CalendarType.Administrative, "Transformative Wellness"
        )
        assert result == "match"


def test_existing_calendar_id_no_location_match_returns_none():
    cal = MagicMock()
    cal.id = "wrong-loc"
    cal.title = "John Harris MD: Admin: Other Location"

    with patch("drag_drop_availability.api.calendar.Calendar") as mock_cal:
        mock_cal.objects.filter.return_value.order_by.return_value = [cal]
        result = _existing_calendar_id(
            "staff-uuid", CalendarType.Administrative, "Transformative Wellness"
        )
        assert result is None
