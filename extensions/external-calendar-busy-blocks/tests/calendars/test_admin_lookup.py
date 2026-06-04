from unittest.mock import MagicMock, patch

from external_calendar_busy_blocks.calendars.admin_lookup import find_admin_calendar_id


def test_returns_id_when_calendar_exists() -> None:
    staff = MagicMock(full_name="Jane Doe")
    queryset = MagicMock()
    queryset.values_list.return_value.last.return_value = "calendar-123"
    with patch(
        "external_calendar_busy_blocks.calendars.admin_lookup.Calendar"
    ) as MockCalendar:
        MockCalendar.objects.for_calendar_name.return_value = queryset
        result = find_admin_calendar_id(staff)
    assert result == "calendar-123"
    MockCalendar.objects.for_calendar_name.assert_called_once()
    args, kwargs = MockCalendar.objects.for_calendar_name.call_args
    assert kwargs["provider_name"] == "Jane Doe"
    assert str(kwargs["calendar_type"]) == "Admin"
    assert kwargs["location"] is None


def test_returns_none_when_no_calendar() -> None:
    staff = MagicMock(full_name="Jane Doe")
    queryset = MagicMock()
    queryset.values_list.return_value.last.return_value = None
    with patch(
        "external_calendar_busy_blocks.calendars.admin_lookup.Calendar"
    ) as MockCalendar:
        MockCalendar.objects.for_calendar_name.return_value = queryset
        result = find_admin_calendar_id(staff)
    assert result is None
