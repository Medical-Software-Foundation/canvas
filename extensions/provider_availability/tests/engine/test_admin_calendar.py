"""Tests for provider_availability.engine.admin_calendar."""

from unittest.mock import MagicMock, call, patch

from provider_availability.engine.admin_calendar import (
    get_admin_calendar_id,
    get_admin_calendars,
)


AC_MODULE = "provider_availability.engine.admin_calendar"


class TestGetAdminCalendarId:
    def test_existing_calendar(self):
        mock_staff = MagicMock()
        mock_staff.full_name = "Jane Doe"

        mock_cal = MagicMock()
        mock_cal.id = "cal-uuid-123"

        with patch(f"{AC_MODULE}.Staff.objects") as mock_staff_objects, \
             patch(f"{AC_MODULE}.CalendarModel.objects") as mock_cal_objects:
            mock_staff_objects.get.return_value = mock_staff
            mock_cal_objects.for_calendar_name.return_value.first.return_value = mock_cal

            cal_id, effects = get_admin_calendar_id("p1")

            assert mock_staff_objects.mock_calls == [call.get(id="p1")]
            assert cal_id == str(mock_cal.id)
            assert effects == []

    def test_creates_new_calendar(self):
        mock_staff = MagicMock()
        mock_staff.full_name = "Jane Doe"

        with patch(f"{AC_MODULE}.Staff.objects") as mock_staff_objects, \
             patch(f"{AC_MODULE}.CalendarModel.objects") as mock_cal_objects, \
             patch(f"{AC_MODULE}.uuid.uuid4", return_value="new-cal-id"):
            mock_staff_objects.get.return_value = mock_staff
            mock_cal_objects.for_calendar_name.return_value.first.return_value = None

            cal_id, effects = get_admin_calendar_id("p1")

            assert cal_id == "new-cal-id"
            assert len(effects) == 1

    def test_existing_calendar_with_location(self):
        mock_staff = MagicMock()
        mock_staff.full_name = "Jane Doe"

        mock_loc = MagicMock()
        mock_loc.full_name = "Main Office"

        mock_cal = MagicMock()
        mock_cal.id = "cal-uuid-loc"

        with patch(f"{AC_MODULE}.Staff.objects") as mock_staff_objects, \
             patch(f"{AC_MODULE}.PracticeLocation.objects") as mock_loc_objects, \
             patch(f"{AC_MODULE}.CalendarModel.objects") as mock_cal_objects:
            mock_staff_objects.get.return_value = mock_staff
            mock_loc_objects.get.return_value = mock_loc
            mock_cal_objects.for_calendar_name.return_value.first.return_value = mock_cal

            cal_id, effects = get_admin_calendar_id("p1", "loc-1")

            assert cal_id == str(mock_cal.id)
            assert effects == []
            mock_cal_objects.for_calendar_name.assert_called_once()

    def test_creates_new_calendar_with_location(self):
        mock_staff = MagicMock()
        mock_staff.full_name = "Jane Doe"

        mock_loc = MagicMock()
        mock_loc.full_name = "Main Office"

        with patch(f"{AC_MODULE}.Staff.objects") as mock_staff_objects, \
             patch(f"{AC_MODULE}.PracticeLocation.objects") as mock_loc_objects, \
             patch(f"{AC_MODULE}.CalendarModel.objects") as mock_cal_objects, \
             patch(f"{AC_MODULE}.uuid.uuid4", return_value="new-cal-loc"):
            mock_staff_objects.get.return_value = mock_staff
            mock_loc_objects.get.return_value = mock_loc
            mock_cal_objects.for_calendar_name.return_value.first.return_value = None

            cal_id, effects = get_admin_calendar_id("p1", "loc-1")

            assert cal_id == "new-cal-loc"
            assert len(effects) == 1

    def test_staff_not_found(self):
        from canvas_sdk.v1.data.staff import Staff

        with patch(f"{AC_MODULE}.Staff.objects") as mock_staff_objects:
            mock_staff_objects.get.side_effect = Staff.DoesNotExist

            cal_id, effects = get_admin_calendar_id("p1")

            assert cal_id == ""
            assert effects == []

    def test_empty_provider_name(self):
        mock_staff = MagicMock()
        mock_staff.full_name = ""

        with patch(f"{AC_MODULE}.Staff.objects") as mock_staff_objects:
            mock_staff_objects.get.return_value = mock_staff

            cal_id, effects = get_admin_calendar_id("p1")

            assert cal_id == ""
            assert effects == []


class TestGetAdminCalendars:
    def test_returns_calendars(self):
        mock_staff = MagicMock()
        mock_staff.full_name = "Jane Doe"
        mock_cal = MagicMock()

        with patch(f"{AC_MODULE}.Staff.objects") as mock_staff_objects, \
             patch(f"{AC_MODULE}.CalendarModel.objects") as mock_cal_objects:
            mock_staff_objects.get.return_value = mock_staff
            mock_cal_objects.filter.return_value = [mock_cal]

            result = get_admin_calendars("p1")

            assert len(result) == 1

    def test_staff_not_found(self):
        from canvas_sdk.v1.data.staff import Staff

        with patch(f"{AC_MODULE}.Staff.objects") as mock_staff_objects:
            mock_staff_objects.get.side_effect = Staff.DoesNotExist

            result = get_admin_calendars("p1")

            assert result == []

    def test_empty_provider_name(self):
        mock_staff = MagicMock()
        mock_staff.full_name = ""

        with patch(f"{AC_MODULE}.Staff.objects") as mock_staff_objects:
            mock_staff_objects.get.return_value = mock_staff

            result = get_admin_calendars("p1")

            assert result == []
